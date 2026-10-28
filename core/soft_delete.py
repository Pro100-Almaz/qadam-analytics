"""Soft deletion: the tree walker, batch restore, purge and the registry.

Spec 0014. A soft delete hides the same rows a hard delete would remove, and
restores them as one unit:

* **Walk.** From the rows being deleted, follow every `CASCADE` edge to live
  rows of soft-deletable models, and recurse. `SET_NULL` / `DO_NOTHING` rows
  are left untouched, so a restore relinks them for free. A live `PROTECT` /
  `RESTRICT` dependent refuses the whole delete, as a hard delete would
  (AC-13). Rows already deleted are skipped and keep their old batch (AC-3).
* **Stamp.** One `UPDATE` per model, all rows sharing one `deletion_batch`.
  `update()` skips `save()` on purpose: no snapshot guard, no homework sync
  echo, no history rows (a stated non-goal).
* **Restore** brings back exactly one batch, after two guards: no row may come
  back under a `CASCADE` parent that is still deleted (AC-4), and no row may
  collide with a live row on a live-only unique rule (AC-5).
* **Purge** is Django's real delete over a batch. Postgres-side cascades and
  `pre_delete` receivers (homework files) run as for any hard delete.

Everything here reads through `_base_manager`: which rows belong to a tree is
a fact about the data, not about the school the caller is scoped to.
"""

import uuid
from collections import defaultdict

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, router, transaction
from django.db.models.deletion import Collector, ProtectedError
from django.utils import timezone


def is_soft_deletable(model):
    from core.models import SoftDeleteMixin
    return isinstance(model, type) and issubclass(model, SoftDeleteMixin)


def soft_delete_models():
    """Every concrete soft-deletable model. Proxies share their parent's rows."""
    return [
        model for model in apps.get_models()
        if is_soft_deletable(model) and not model._meta.proxy
    ]


def _concrete(model):
    return model._meta.concrete_model


def _reverse_fk_relations(model):
    """Reverse one-to-many / one-to-one relations onto `model`, M2M excluded.

    M2M through rows are a non-goal: they stay as they are and are simply
    there again on restore.
    """
    for rel in model._meta.related_objects:
        if rel.many_to_many or rel.field.many_to_many:
            continue
        yield rel


def _label(model, pk):
    return f'{model._meta.verbose_name} #{pk}'


def collect(objs, extras=True):
    """`{concrete model: set of pks}` a soft delete of `objs` would stamp.

    Raises ProtectedError if a live `PROTECT` / `RESTRICT` dependent outside
    the tree would be left pointing at a hidden row.
    """
    found = defaultdict(set)
    pending = defaultdict(set)
    for obj in objs:
        if not obj.is_deleted:
            pending[_concrete(type(obj))].add(obj.pk)

    while pending:
        model, pks = pending.popitem()
        new = pks - found[model]
        if not new:
            continue
        found[model] |= new
        for rel in _reverse_fk_relations(model):
            child = _concrete(rel.related_model)
            if rel.on_delete is not models.CASCADE or not is_soft_deletable(child):
                # A hard-delete model on a CASCADE edge is left alone; the
                # softdelete.E001 check is what makes that deliberate.
                continue
            child_pks = child._base_manager.filter(
                **{f'{rel.field.name}__in': new}, is_deleted=False,
            ).values_list('pk', flat=True)
            pending[child].update(child_pks)
        if extras:
            for extra_model, extra_pks in model.soft_delete_extra(new):
                pending[_concrete(extra_model)].update(extra_pks)

    found = {model: pks for model, pks in found.items() if pks}
    _raise_if_protected(found)
    return found


def _raise_if_protected(found):
    protected = []
    for model, pks in found.items():
        for rel in _reverse_fk_relations(model):
            if rel.on_delete not in (models.PROTECT, models.RESTRICT):
                continue
            child = _concrete(rel.related_model)
            dependents = child._base_manager.filter(**{f'{rel.field.name}__in': pks})
            if is_soft_deletable(child):
                dependents = dependents.filter(is_deleted=False).exclude(
                    pk__in=found.get(child, ()),
                )
            protected.extend(dependents[:20])
    if protected:
        names = ', '.join(_label(type(obj), obj.pk) for obj in protected[:5])
        raise ProtectedError(
            f'Cannot delete: protected rows still refer to it ({names}).',
            set(protected),
        )


def soft_delete(objs, user=None, extras=True):
    """Soft-delete `objs` and their cascade tree as one batch.

    Returns `(count, {model label: count})`, the shape `Model.delete()` has.
    """
    objs = list(objs)
    if not objs:
        return 0, {}
    using = router.db_for_write(type(objs[0]))
    user_id = getattr(user, 'pk', None)
    with transaction.atomic(using=using):
        found = collect(objs, extras=extras)
        batch = uuid.uuid4()
        now = timezone.now()
        counts = {}
        for model, pks in found.items():
            counts[model._meta.label] = model._base_manager.filter(
                pk__in=pks, is_deleted=False,
            ).update(
                is_deleted=True, deleted_at=now,
                deleted_by_id=user_id, deletion_batch=batch,
            )
    for obj in objs:
        if obj.pk in found.get(_concrete(type(obj)), ()):
            obj.is_deleted = True
            obj.deleted_at = now
            obj.deleted_by_id = user_id
            obj.deletion_batch = batch
    return sum(counts.values()), counts


# ── Batches ──

def batch_rows(batch_id):
    """`{model: set of pks}` of every row in one batch, any school."""
    rows = {}
    for model in soft_delete_models():
        pks = set(model._base_manager.filter(
            deletion_batch=batch_id, is_deleted=True,
        ).values_list('pk', flat=True))
        if pks:
            rows[model] = pks
    return rows


def _cascade_fks(model):
    """Forward FKs of `model` whose parent is soft-deletable and CASCADEs here."""
    for field in model._meta.concrete_fields:
        if not field.many_to_one and not field.one_to_one:
            continue
        if field.remote_field.on_delete is not models.CASCADE:
            continue
        if is_soft_deletable(_concrete(field.related_model)):
            yield field


def batch_roots(rows):
    """`{model: pks}` of the rows in `rows` whose deletion started the batch.

    A row is a root when no `CASCADE` parent of it is in the same batch. The
    mirror rows `soft_delete_extra` adds count as roots too: nothing in the
    batch points at them by FK.
    """
    roots = {}
    for model, pks in rows.items():
        children = set()
        for field in _cascade_fks(model):
            parent_pks = rows.get(_concrete(field.related_model))
            if parent_pks:
                children |= set(model._base_manager.filter(
                    pk__in=pks, **{f'{field.attname}__in': parent_pks},
                ).values_list('pk', flat=True))
        if pks - children:
            roots[model] = pks - children
    return roots


def _check_parents_live(rows):
    """AC-4: refuse to restore a row under a CASCADE parent that stays deleted."""
    for model, pks in rows.items():
        for field in _cascade_fks(model):
            parent = _concrete(field.related_model)
            parent_ids = set(model._base_manager.filter(pk__in=pks).exclude(
                **{f'{field.attname}__isnull': True},
            ).values_list(field.attname, flat=True))
            parent_ids -= rows.get(parent, set())
            dead = parent._base_manager.filter(
                pk__in=parent_ids, is_deleted=True,
            ).first()
            if dead is not None:
                raise ValidationError(
                    f'Cannot restore {model._meta.verbose_name}: its '
                    f'{field.verbose_name} "{dead}" ({_label(parent, dead.pk)}) '
                    f'is deleted. Restore that first.'
                )


def _without_is_deleted(condition):
    """`condition` minus its `is_deleted=False` term, or None if nothing is left."""
    if condition.connector != models.Q.AND or condition.negated:
        return condition
    rest = [c for c in condition.children if c != ('is_deleted', False)]
    if not rest:
        return None
    return models.Q(*rest)


def _live_unique_constraints(model):
    for constraint in model._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint):
            continue
        if not constraint.fields or constraint.condition is None:
            continue
        if ('is_deleted', False) in constraint.condition.children:
            yield constraint


def _check_unique_free(rows):
    """AC-5: refuse to restore a row whose unique value a live row now holds."""
    for model, pks in rows.items():
        for constraint in _live_unique_constraints(model):
            attnames = [model._meta.get_field(f).attname for f in constraint.fields]
            candidates = model._base_manager.filter(pk__in=pks)
            rest = _without_is_deleted(constraint.condition)
            if rest is not None:
                candidates = candidates.filter(rest)
            for values in candidates.values_list('pk', *attnames):
                pk, values = values[0], values[1:]
                if any(v is None for v in values):
                    continue  # NULLs never collide in a Postgres unique index
                conflict = model._base_manager.filter(constraint.condition).filter(
                    **dict(zip(attnames, values)),
                ).exclude(pk__in=pks).first()
                if conflict is not None:
                    raise ValidationError(
                        f'Cannot restore {_label(model, pk)}: '
                        f'{_label(model, conflict.pk)} ("{conflict}") now holds '
                        f'the same {", ".join(constraint.fields)}. Delete or '
                        f'change it first.'
                    )


def restore_rows(rows):
    if not rows:
        return
    using = router.db_for_write(next(iter(rows)))
    try:
        with transaction.atomic(using=using):
            _check_parents_live(rows)
            _check_unique_free(rows)
            for model, pks in rows.items():
                model._base_manager.filter(pk__in=pks).update(
                    is_deleted=False, deleted_at=None,
                    deleted_by=None, deletion_batch=None,
                )
    except IntegrityError as exc:
        # The checks above name the row in the normal case; this is a race
        # with a write that landed between them and the UPDATE.
        raise ValidationError(f'Cannot restore: {exc}') from exc


def restore(obj):
    """Restore `obj` and every row deleted together with it."""
    if not obj.is_deleted:
        return
    if obj.deletion_batch is None:
        # Deleted before spec 0014: a batch of one.
        rows = {_concrete(type(obj)): {obj.pk}}
    else:
        rows = batch_rows(obj.deletion_batch)
    restore_rows(rows)
    obj.is_deleted = False
    obj.deleted_at = None
    obj.deleted_by_id = None
    obj.deletion_batch = None


def restore_batch(batch_id):
    restore_rows(batch_rows(batch_id))


def purge_rows(rows):
    """Hard-delete every row in `rows`, with Django's cascade."""
    if not rows:
        return 0, {}
    using = router.db_for_write(next(iter(rows)))
    collector = Collector(using=using, origin=None)
    with transaction.atomic(using=using):
        for model, pks in rows.items():
            collector.collect(list(model._base_manager.filter(pk__in=pks)))
        return collector.delete()


def purge_batch(batch_id):
    return purge_rows(batch_rows(batch_id))
