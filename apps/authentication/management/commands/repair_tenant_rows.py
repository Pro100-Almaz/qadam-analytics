"""Find — and optionally repair — rows that predate the phase 6 rules.

`SchoolConsistentModel` and `SchoolDerivedMixin` govern *writes*. They say
nothing about the rows already in the table, and phase 1 left known residue:
every `Subject`, `SchoolGroup`, `PsychologicalStateTemplates`, `Club` and
`Attachment` was backfilled onto the default tenant because nothing in the data
said otherwise. School #2 therefore sees an empty subject catalogue, and its
offerings point at school #1's subjects — which is exactly what makes
`home/0040_composite_school_fks` refuse to apply.

This is the read-side twin of those rules: it re-runs them over existing rows.

    python manage.py repair_tenant_rows              # report only
    python manage.py repair_tenant_rows --apply      # write the safe fixes
    python manage.py repair_tenant_rows --apply --clone-missing

**Which school is right?** Never guessed — one authority per row, and it is
the row's derivation source: `SCHOOL_DERIVED_FROM` where the model has one,
its `SCHOOL_PATH` otherwise. So for a `SubjectOffering` `class_group` wins
(which is what the phase-1 backfill used), and for a `Student`, `user` does.

The ordering matters and is not the obvious one. Reading the denormalised
`school` column first would make a *stale column* blame every parent of the
row — and the stale column is the commoner residue, because the column is the
thing phase 1 had to guess at while the parents were already right.

**Two repairs are safe and one is not.**

* Re-stamping a denormalised `school` column from its derivation source is
  safe: the mixin would have written that value, and the row's own column is
  the only thing that changes.
* Re-pointing a cross-school FK at the *same-named* row in the correct school
  is safe when such a row exists — the twin is matched on a declared natural
  key, never on id.
* Creating the twin when it does not exist is **not** safe to do silently: it
  is a judgement about what the other school's catalogue should contain. It is
  behind `--clone-missing`, and only for the models where a twin is a copy of
  a catalogue entry rather than a piece of history.

Anything that fits none of those is reported and left alone. Exits 1 when
findings remain, so it can gate a deploy.
"""

from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, IntegerField
from django.db.models.functions import Coalesce

from core.checks import _tenant_models
from core.models import school_id_of, school_id_through
from core.tenancy import (
    CrossSchoolWriteError, SchoolDerivationError, all_schools,
)

#: How to recognise "the same row, in the other school". Matched on a natural
#: key rather than on id, because the whole point is that the id belongs to the
#: wrong tenant. A model absent from here is never auto-re-pointed.
TWIN_KEYS = {
    'home.Subject': ('name', 'language_group'),
    'authentication.SchoolGroup': ('name',),
    'home.AcademicYear': ('year',),
    'authentication.PsychologicalStateTemplates': ('name',),
}

#: Models whose twin may be *created* under --clone-missing. Catalogue rows
#: only: copying a Subject into the school that offers it is what the phase-1
#: residue note asked for by hand. An AcademicYear is deliberately absent —
#: cloning one means choosing quarter dates and an active flag, which
#: `home/0038` does properly and this must not second-guess.
CLONEABLE = frozenset({
    'home.Subject',
    'authentication.SchoolGroup',
    'authentication.PsychologicalStateTemplates',
})

#: Fields never copied into a twin: identity, audit trail, and the tenancy
#: column itself, which is the one thing being changed.
NEVER_CLONED = frozenset({'id', 'pk', 'school', 'school_id', 'uuid', 'created_at'})


class Finding:
    def __init__(self, obj, field, home_school, wrong_school, action, detail=''):
        self.obj = obj
        self.field = field
        self.home_school = home_school
        self.wrong_school = wrong_school
        self.action = action          # 'stamp' | 'repoint' | 'clone' | 'manual'
        self.detail = detail

    @property
    def label(self):
        return f'{type(self.obj)._meta.label} #{self.obj.pk}'


class Command(BaseCommand):
    help = 'Report (and optionally repair) cross-tenant rows left by phase 1.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the safe repairs. Without it, nothing is changed.',
        )
        parser.add_argument(
            '--clone-missing', action='store_true',
            help=(
                'Also create a twin in the correct school when none exists. '
                'Catalogue models only; see CLONEABLE.'
            ),
        )
        parser.add_argument(
            '--model', action='append', default=[],
            help='Limit to these labels, e.g. --model home.SubjectOffering.',
        )
        parser.add_argument(
            '--limit-examples', type=int, default=10,
            help='How many example rows to print per model (default 10).',
        )

    def handle(self, *args, **options):
        only = set(options['model'])
        findings = []

        # all_schools(), and nothing narrower: a row misfiled into school A is
        # invisible from school B, so scanning school by school would find
        # exactly the rows that are already correct.
        with all_schools():
            for model in _tenant_models():
                if only and model._meta.label not in only:
                    continue
                if model._meta.proxy:
                    continue  # the concrete parent covers the same table
                findings.extend(self._scan(model))

            self._report(findings, options['limit_examples'])

            if not findings:
                self.stdout.write(self.style.SUCCESS(
                    '\nNo cross-tenant rows. home/0040 will apply.'
                ))
                return

            if not options['apply']:
                self.stdout.write(self.style.WARNING(
                    '\nReport only. Re-run with --apply to write the repairs '
                    'marked stamp/repoint above.'
                ))
                raise SystemExit(1)

            remaining = self._apply(findings, options['clone_missing'])

        if remaining:
            self.stdout.write(self.style.ERROR(
                f'\n{remaining} row(s) still need a human decision.'
            ))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('\nAll findings repaired.'))

    # ── scanning ────────────────────────────────────────────────────────────

    def _scan(self, model):
        """Every row whose declared FKs or own column disagree with its tenant.

        Set-based, and it has to be. The first version asked the question one
        row at a time — one or more queries per row, which is invisible on a
        dev database and, on 50k grades over a container network, looks exactly
        like a hang. Here each check is a single query with the comparison in
        the WHERE clause, so a model costs one round trip rather than one per
        row, and only the rows that *are* findings are ever loaded.

        `_base_manager`: unscoped and unfiltered, so soft-deleted rows are
        included. A deleted row still holds a FK the composite constraint will
        check, so skipping it would let the deploy fail on something this
        command reported as clean.
        """
        declared = tuple(getattr(model, 'SCHOOL_CONSISTENT_FIELDS', ()))
        derived_from = tuple(getattr(model, 'SCHOOL_DERIVED_FROM', ()))
        if not declared and not derived_from:
            return []

        home = self._home_expression(model, derived_from)
        if home is None:
            # Nothing expressible as a join — a GenericForeignKey source, which
            # only Attachment has. Small table, and correctness beats speed.
            return self._scan_row_by_row(model, declared, derived_from)

        base = model._base_manager.annotate(_home=home)
        findings = []

        findings += [
            Finding(obj, '(row)', None, None, 'manual',
                    'reaches no school at all — its derivation and its '
                    'SCHOOL_PATH both resolve to NULL')
            for obj in base.filter(_home__isnull=True)
        ]

        if any(f.name == 'school' for f in model._meta.fields):
            # A stale denormalised column: it disagrees with the parent it is
            # a copy of. `exclude` rather than a `!=` filter because NULL on
            # either side is not a disagreement, it is a different finding.
            findings += [
                Finding(obj, 'school', obj._home, obj.school_id, 'stamp')
                for obj in base.filter(
                    _home__isnull=False, school__isnull=False,
                ).exclude(school=F('_home'))
            ]

        for field in declared:
            path = self._field_school_path(model, field)
            if path is None:
                continue
            rows = (
                base.annotate(_other=F(path))
                .filter(_home__isnull=False, _other__isnull=False)
                .exclude(_other=F('_home'))
            )
            findings += [
                Finding(obj, field, obj._home, obj._other, 'repoint')
                for obj in rows
            ]
        return findings

    @staticmethod
    def _school_path_of(model):
        """The lookup from `model` to its school, or None."""
        path = getattr(model, 'SCHOOL_PATH', None)
        if not path or not path.split('__')[-1] == 'school':
            return None
        return path

    @classmethod
    def _field_school_path(cls, model, field_name):
        """The lookup from `model` to the school of one declared field.

        `Student.school_group` + `SchoolGroup.SCHOOL_PATH = 'school'` gives
        `school_group__school`. A GenericForeignKey has no such path and comes
        back None — the caller falls back to walking rows.
        """
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return None
        if not (field.is_relation and field.concrete and field.related_model):
            return None
        target = cls._school_path_of(field.related_model)
        return f'{field_name}__{target}' if target else None

    @classmethod
    def _home_expression(cls, model, derived_from):
        """Which school this row belongs to, as something SQL can evaluate.

        `Coalesce` is the ORM's version of "the first source that resolves
        wins", which is precisely `SchoolDerivedMixin`'s rule — so the
        expression and the mixin cannot drift apart. The model's own
        SCHOOL_PATH goes last, as the fallback for a root or for a row whose
        every derivation source is empty.
        """
        paths = []
        for source in derived_from:
            try:
                related = model
                for part in source.split('__'):
                    related = related._meta.get_field(part).related_model
            except Exception:
                return None      # GenericForeignKey, or an unresolvable path
            target = cls._school_path_of(related)
            if target is None:
                return None
            paths.append(f'{source}__{target}')

        own = cls._school_path_of(model)
        if own:
            paths.append(own)
        if not paths:
            return None
        if len(paths) == 1:
            return F(paths[0])
        return Coalesce(*[F(p) for p in paths], output_field=IntegerField())

    @staticmethod
    def _home_school(obj, derived_from):
        """The row-by-row twin of `_home_expression`. Same authority order.

        The derivation source outranks the denormalised column, because that is
        `SchoolDerivedMixin`'s own rule: the column is a cache of the parent,
        and a cache that disagrees with its source is the thing that is stale.
        Reading the column first would invert that and blame every parent of a
        row whose column had gone bad — which is the commoner residue, since
        the column is what phase 1 had to guess at.
        """
        if derived_from:
            derived = obj._derive_school_id()
            if derived is not None:
                return derived
        return school_id_of(obj)

    def _scan_row_by_row(self, model, declared, derived_from):
        """The fallback for a model whose sources are not joinable."""
        findings = []
        for obj in model._base_manager.all().iterator(chunk_size=500):
            home = self._home_school(obj, derived_from)
            if home is None:
                findings.append(Finding(
                    obj, '(row)', None, None, 'manual',
                    'reaches no school at all',
                ))
                continue
            own = getattr(obj, 'school_id', None)
            if own is not None and own != home:
                findings.append(Finding(obj, 'school', home, own, 'stamp'))
            for field in declared:
                other = school_id_through(obj, field)
                if other is not None and other != home:
                    findings.append(Finding(obj, field, home, other, 'repoint'))
        return findings

    # ── reporting ───────────────────────────────────────────────────────────

    def _report(self, findings, limit):
        by_model = {}
        for finding in findings:
            by_model.setdefault(type(finding.obj)._meta.label, []).append(finding)
        for label in sorted(by_model):
            group = by_model[label]
            self.stdout.write(self.style.WARNING(
                f'\n{label}: {len(group)} cross-tenant reference(s)'
            ))
            for finding in group[:limit]:
                self.stdout.write(
                    f'  #{finding.obj.pk}  {finding.field}: '
                    f'school #{finding.wrong_school} -> should be '
                    f'#{finding.home_school}'
                    + (f'  [{finding.detail}]' if finding.detail else '')
                )
            if len(group) > limit:
                self.stdout.write(f'  … and {len(group) - limit} more')

    # ── repairing ───────────────────────────────────────────────────────────

    def _apply(self, findings, clone_missing):
        remaining = 0
        for finding in findings:
            # A savepoint per finding: one row that cannot be repaired must not
            # take the other 300 with it, and a repair that trips the phase 6
            # write rules is exactly the signal that this row needs a person
            # rather than a bigger hammer.
            try:
                with transaction.atomic():
                    if finding.action == 'stamp':
                        finding.obj.school_id = finding.home_school
                        finding.obj.save(update_fields=['school'])
                        self._say('stamped', finding)
                    elif finding.action == 'repoint':
                        if not self._repoint(finding, clone_missing):
                            remaining += 1
                    else:
                        self._say('LEFT ALONE', finding, style=self.style.ERROR)
                        remaining += 1
            except (CrossSchoolWriteError, SchoolDerivationError) as exc:
                self._say(f'LEFT ALONE ({exc})', finding, style=self.style.ERROR)
                remaining += 1
        return remaining

    def _repoint(self, finding, clone_missing):
        obj, field = finding.obj, finding.field
        current = getattr(obj, field, None)
        if current is None:
            return False
        target_model = type(current)
        label = target_model._meta.label
        keys = TWIN_KEYS.get(label)
        if not keys:
            self._say(
                'LEFT ALONE (no twin key)', finding, style=self.style.ERROR)
            return False

        lookup = {key: getattr(current, key) for key in keys}
        twin = target_model._base_manager.filter(
            school_id=finding.home_school, **lookup).first()

        if twin is None:
            if not (clone_missing and label in CLONEABLE):
                self._say(
                    f'LEFT ALONE (no {label} matching {lookup} in school '
                    f'#{finding.home_school}; --clone-missing would create it)'
                    if label in CLONEABLE else
                    f'LEFT ALONE (no twin in school #{finding.home_school}, '
                    f'and {label} is not cloneable)',
                    finding, style=self.style.ERROR)
                return False
            twin = self._clone(current, finding.home_school)
            self._say(f'cloned {label} #{current.pk} -> #{twin.pk}', finding)

        setattr(obj, field, twin)
        obj.save()
        self._say(f'repointed at {label} #{twin.pk}', finding)
        return True

    def _clone(self, source, school_id):
        """A copy of `source` in another school, minus identity and audit."""
        fields = {
            f.attname: getattr(source, f.attname)
            for f in source._meta.fields
            if f.concrete and f.name not in NEVER_CLONED
            and f.attname not in NEVER_CLONED
        }
        fields['school_id'] = school_id
        return type(source)._base_manager.create(**fields)

    def _say(self, what, finding, style=None):
        style = style or self.style.SUCCESS
        self.stdout.write(style(
            f'  {finding.label} {finding.field}: {what}'
        ))
