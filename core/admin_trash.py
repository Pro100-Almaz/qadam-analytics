"""The admin trash: list, restore and purge soft-deleted rows (spec 0013, AC-11).

    /admin/trash/                              counts per model
    /admin/trash/<app>/<model>/                that model's rows, by batch
    /admin/trash/batch/<uuid>/restore/         POST: bring the batch back
    /admin/trash/batch/<uuid>/purge/           GET: confirm; POST: hard-delete

**Everything reads `all_objects`**, which keeps deleted rows but stays scoped to
the school in the header. A batch is looked up the same way, so a batch id
from another tenant resolves to nothing here and 404s rather than being
restored or purged from the wrong school.

**Rows deleted before spec 0013 have no batch.** They are not backfilled
(spec, Data model), so each one is addressed as a batch of one under a stable
id derived from its model and pk (`legacy_batch_id`). The id is computed, not
stored, so listing the trash never writes.

**Permissions.** Viewing needs `view_<model>`; restoring needs
`change_<model>` for every model in the batch. Purging is the irreversible
one: superusers and the Admin group only, plus `delete_<model>` for every
model in the batch. Anyone else gets 403.
"""

import datetime
import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Max
from django.db.models.deletion import ProtectedError, RestrictedError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.text import capfirst

from core.soft_delete import (
    batch_roots, purge_rows, restore_rows, soft_delete_models,
)

#: Namespace of the computed ids of rows deleted before batches existed.
LEGACY_BATCH_NAMESPACE = uuid.UUID('6f1d5c1e-0d13-4c4e-9a43-5d0f1e7a0013')

BATCHES_PER_PAGE = 25


def legacy_batch_id(model, pk):
    return uuid.uuid5(LEGACY_BATCH_NAMESPACE, f'{model._meta.label}:{pk}')


def _perm(user, action, model):
    return user.has_perm(f'{model._meta.app_label}.{action}_{model._meta.model_name}')


def can_purge(user):
    return user.is_superuser or user.is_admin()


def _dead(model):
    return model.all_objects.filter(is_deleted=True)


def scoped_batch_rows(batch_id):
    """`{model: pks}` of one batch, limited to the active school."""
    rows = {}
    for model in soft_delete_models():
        pks = set(_dead(model).filter(deletion_batch=batch_id).values_list('pk', flat=True))
        if pks:
            rows[model] = pks
    if rows:
        return rows
    for model in soft_delete_models():
        for pk in _dead(model).filter(deletion_batch__isnull=True).values_list('pk', flat=True):
            if legacy_batch_id(model, pk) == batch_id:
                return {model: {pk}}
    return {}


def _rows_or_404(batch_id):
    rows = scoped_batch_rows(batch_id)
    if not rows:
        raise Http404('No such batch in the trash of this school.')
    return rows


def _require(user, action, rows):
    missing = [m._meta.verbose_name for m in rows if not _perm(user, action, m)]
    if missing:
        raise PermissionDenied(f'Missing {action} permission for: {", ".join(missing)}')


def _summary(rows):
    """`[(verbose_name_plural, count)]`, largest first."""
    return sorted(
        ((capfirst(m._meta.verbose_name_plural), len(pks)) for m, pks in rows.items()),
        key=lambda item: -item[1],
    )


def _back(request):
    target = request.POST.get('next') or ''
    index = reverse('admin:trash_index')
    return target if target.startswith(index) else index


class TrashViews:
    """Bound to one AdminSite for its context (header, switcher) and URL names."""

    def __init__(self, admin_site):
        self.site = admin_site

    def get_urls(self):
        view = self.site.admin_view
        return [
            path('trash/', view(self.index), name='trash_index'),
            path(
                'trash/batch/<uuid:batch_id>/restore/',
                view(self.restore), name='trash_restore',
            ),
            path(
                'trash/batch/<uuid:batch_id>/purge/',
                view(self.purge), name='trash_purge',
            ),
            path(
                'trash/<str:app_label>/<str:model_name>/',
                view(self.model_trash), name='trash_model',
            ),
        ]

    def _context(self, request, title, **extra):
        return {**self.site.each_context(request), 'title': title, **extra}

    def index(self, request):
        models = []
        for model in soft_delete_models():
            if not _perm(request.user, 'view', model):
                continue
            count = _dead(model).count()
            if count:
                models.append({
                    'name': capfirst(model._meta.verbose_name_plural),
                    'app': model._meta.app_config.verbose_name,
                    'count': count,
                    'url': reverse('admin:trash_model', args=[
                        model._meta.app_label, model._meta.model_name,
                    ]),
                })
        models.sort(key=lambda m: (m['app'], m['name']))
        return render(request, 'admin/trash/index.html', self._context(
            request, 'Trash', models=models,
        ))

    def model_trash(self, request, app_label, model_name):
        model = next((
            m for m in soft_delete_models()
            if (m._meta.app_label, m._meta.model_name) == (app_label, model_name)
        ), None)
        if model is None:
            raise Http404('Not a soft-deletable model.')
        if not _perm(request.user, 'view', model):
            raise PermissionDenied

        batched = (
            _dead(model).exclude(deletion_batch__isnull=True)
            .values('deletion_batch').annotate(at=Max('deleted_at'))
            .order_by('-at')
        )
        keys = [(row['deletion_batch'], row['at']) for row in batched]
        legacy = _dead(model).filter(deletion_batch__isnull=True).order_by('-deleted_at')
        keys += [
            (legacy_batch_id(model, pk), at)
            for pk, at in legacy.values_list('pk', 'deleted_at')
        ]
        oldest = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        keys.sort(key=lambda key: key[1] or oldest, reverse=True)

        page = Paginator(keys, BATCHES_PER_PAGE).get_page(request.GET.get('page'))
        batches = [self._batch(batch_id, model) for batch_id, _ in page]
        return render(request, 'admin/trash/model.html', self._context(
            request, f'Trash: {model._meta.verbose_name_plural}',
            model_name=capfirst(model._meta.verbose_name_plural),
            batches=batches, page=page, can_purge=can_purge(request.user),
        ))

    def _batch(self, batch_id, model):
        rows = scoped_batch_rows(batch_id)
        roots = batch_roots(rows) or rows
        root_objs = [
            obj for root_model, pks in roots.items()
            for obj in root_model._base_manager.filter(pk__in=pks).select_related('deleted_by')[:10]
        ]
        first = root_objs[0] if root_objs else None
        return {
            'id': batch_id,
            'deleted_at': first.deleted_at if first else None,
            'deleted_by': first.deleted_by if first else None,
            'roots': [f'{capfirst(o._meta.verbose_name)}: {o}' for o in root_objs],
            'here': len(rows.get(model, ())),
            'total': sum(len(pks) for pks in rows.values()),
            'summary': _summary(rows),
        }

    @staticmethod
    def restore(request, batch_id):
        if request.method != 'POST':
            return HttpResponseRedirect(reverse('admin:trash_index'))
        rows = _rows_or_404(batch_id)
        _require(request.user, 'change', rows)
        try:
            restore_rows(rows)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            count = sum(len(pks) for pks in rows.values())
            messages.success(request, f'Restored {count} row(s).')
        return HttpResponseRedirect(_back(request))

    def purge(self, request, batch_id):
        if not can_purge(request.user):
            raise PermissionDenied('Only administrators can purge the trash.')
        rows = _rows_or_404(batch_id)
        _require(request.user, 'delete', rows)
        if request.method != 'POST':
            return render(request, 'admin/trash/purge_confirm.html', self._context(
                request, 'Purge from trash',
                batch_id=batch_id, summary=_summary(rows),
                next=request.GET.get('next', ''),
            ))
        try:
            purge_rows(rows)
        except (ProtectedError, RestrictedError) as exc:
            messages.error(request, f'Cannot purge: {exc.args[0]}')
        else:
            messages.success(request, 'Purged for good.')
        return HttpResponseRedirect(_back(request))

