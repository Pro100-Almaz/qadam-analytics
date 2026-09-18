"""Two static gates against import-time querysets. Run by CI.

A class body executes once, at **import**. `apply_school_scope` runs inside a
manager's `get_queryset()`, so a queryset built in a class body resolves the
school scope at import time — when there is no request and no scope. That has
two failure modes, and the quiet one is the dangerous one:

* under ``SCHOOL_SCOPE_MODE='enforce'`` it raises during ``django.setup()`` and
  the process will not boot. Loud, immediate, unshippable.
* under ``'off'`` or ``'warn'`` — where the code lives for the whole of phases
  2-4 — nothing raises. The queryset is baked unscoped at import and *stays*
  unscoped for every request in every school. School A's admin gets a picker
  listing school B's students.

Neither the tenancy system checks nor the isolation tests catch the second
case. The checks run after import, by which point the damage is a value rather
than an event; and most of these sites are write-side `PrimaryKeyRelatedField`
querysets, which govern which pks a POST may reference — invisible to a sweep
that reads GET bodies looking for the other school's marker string.

Both rules are syntactic, which is the point: the broken form is also the
idiomatic one (`queryset = Model.objects.all()` is in every DRF tutorial), so
the regression is the default outcome rather than a risk.

---------------------------------------------------------------------------
Rule 1 (``tenancy-lint.W001``) — a queryset built in a class body
---------------------------------------------------------------------------
The distinction is one token::

    student = PrimaryKeyRelatedField(queryset=Student.objects.all())   # broken
    student = PrimaryKeyRelatedField(queryset=Student.objects)         # correct

`RelatedField.get_queryset` does ``queryset.all()`` on whatever it was handed.
On a **Manager** that re-enters ``get_queryset()``, so the scope is applied per
request. On a **QuerySet** it is ``_chain()`` — a clone carrying the WHERE
clause baked at import. Same call, opposite meaning.

A DRF *generic view* is different: ``GenericAPIView.get_queryset`` re-chains
only ``isinstance(queryset, QuerySet)``, so handing it a Manager returns the
Manager itself and pagination breaks on the slice. There the fix is to override
``get_queryset()``, which runs per request.

---------------------------------------------------------------------------
Rule 2 (``tenancy-lint.W002``) — a ModelForm exposing a scoped FK via Meta
---------------------------------------------------------------------------
The same bug one level deeper, with no ``queryset=`` to grep for.
``ModelFormMetaclass`` runs ``fields_for_model`` at class-definition time and
``ForeignKey.formfield()`` resolves ``_default_manager`` right there — so a
tenant FK merely *named in* ``Meta.fields`` bakes an import-time queryset.

This is the variant that crashes ``django.setup()`` before the tenancy system
checks can report anything, so `manage.py check` cannot be the gate for it.

``fields_for_model`` skips any name present in the form's declared fields
(``if f.name in form_declared_fields: ... continue``) before calling
``formfield()``, so an explicitly declared field is safe from this rule — it
falls under rule 1 instead. Assigning ``self.fields[name].queryset`` in
``__init__`` also clears it: the metaclass still built one, but nothing reads it.

Model forms are told apart from DRF ``ModelSerializer`` by their base names, not
by ``Meta.model`` — serializers have that too, but DRF builds fields lazily on
the *instance*, so it has no import-time hazard.

---------------------------------------------------------------------------
Baseline
---------------------------------------------------------------------------
The tree has a known population of these; phase 3 is what converts them. A lint
landed red is a lint that acquires suppressions and dies, so the known sites sit
in ``core/tenancy_lint_baseline.txt`` and only *new* ones fail the build. The
baseline is a ratchet, not an amnesty: a fixed site that is still listed also
fails, so the file shrinks as phase 3 lands and cannot quietly rot.

Suppress a single line with a trailing ``# tenancy-lint: ok`` comment.

Usage::

    python -m core.tenancy_lint                    # CI
    python -m core.tenancy_lint --update-baseline  # after fixing sites
"""

import argparse
import ast
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / 'core' / 'tenancy_lint_baseline.txt'
SCAN_ROOTS = ('apps', 'core')
SKIP_DIR_PARTS = frozenset({'migrations', 'tests', '__pycache__'})
SUPPRESSION = '# tenancy-lint: ok'

#: Manager attributes that apply the school filter. `unscoped` is deliberately
#: outside it: that manager never scopes, so freezing it at import changes
#: nothing about isolation.
SCOPED_MANAGERS = ('objects', 'in_school', 'all_objects', '_default_manager')

W001 = 'tenancy-lint.W001'
W002 = 'tenancy-lint.W002'


class Finding:
    def __init__(self, code, path, lineno, where, detail, hint):
        self.code = code
        self.path = path
        self.lineno = lineno
        self.where = where
        self.detail = detail
        self.hint = hint

    @property
    def key(self):
        """Line-independent identity, so the baseline survives edits above it."""
        return f'{self.code}|{self.path}|{self.where}|{self.detail}'

    def render(self):
        return (
            f'{self.path}:{self.lineno}: {self.code} {self.where}: {self.detail}\n'
            f'    {self.hint}'
        )


def _iter_python_files():
    for root in SCAN_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob('*.py')):
            if SKIP_DIR_PARTS & set(path.parts):
                continue
            yield path


def _rel(path):
    return str(path.relative_to(REPO_ROOT))


def _class_body_statements(cls):
    """Statements that run at import: the class body, methods excluded."""
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield stmt


def _touches_scoped_manager(node):
    src = ast.unparse(node)
    return any(f'.{name}' in src for name in SCOPED_MANAGERS)


def _is_bare_manager(node):
    """`Student.objects` — an attribute access with nothing called on it."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr in SCOPED_MANAGERS
        and isinstance(node.value, (ast.Name, ast.Attribute))
    )


def _check_class_body_querysets(tree, relpath):
    """Rule 1."""
    findings = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for stmt in _class_body_statements(cls):
            # `queryset = Model.objects...` — a DRF generic view attribute.
            if isinstance(stmt, ast.Assign) and any(
                getattr(t, 'id', None) == 'queryset' for t in stmt.targets
            ):
                if _touches_scoped_manager(stmt.value):
                    findings.append(Finding(
                        W001, relpath, stmt.lineno, cls.name,
                        f'queryset = {ast.unparse(stmt.value)}',
                        'GenericAPIView re-chains only a QuerySet, so a Manager '
                        'will not do here — override get_queryset() instead, so '
                        'it resolves per request inside the scope.',
                    ))
            # `field = Something(queryset=Model.objects...)`
            for node in ast.walk(stmt):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != 'queryset' or _is_bare_manager(kw.value):
                        continue
                    if not _touches_scoped_manager(kw.value):
                        continue
                    findings.append(Finding(
                        W001, relpath, kw.value.lineno, cls.name,
                        f'queryset={ast.unparse(kw.value)}',
                        'Pass the Manager, not a QuerySet: `queryset=Model.objects` '
                        '(DRF calls .all() on it per request, which re-enters the '
                        'scope). For a form field use `queryset=None` and set '
                        '`self.fields[...].queryset` in __init__.',
                    ))
    return findings


def _looks_like_model_form(cls):
    """Base named `*Form`. ModelSerializer also has Meta.model but builds its
    fields lazily on the instance, so it carries no import-time hazard."""
    for base in cls.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, 'id', '')
        if name.endswith('Form'):
            return True
    return False


def _literal_names(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [
            e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    return []


def _meta_of(cls):
    for stmt in cls.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == 'Meta':
            return stmt
    return None


def _assignments(cls_or_meta):
    out = {}
    for stmt in cls_or_meta.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = stmt.value
    return out


def _fields_handled_in_init(cls):
    """Names given an explicit queryset inside any method of the class.

    Only literal subscripts are resolved. A loop that assigns querysets by
    computed name reads as unhandled — suppress those with a trailing comment
    rather than widening this, so the rule keeps its teeth.
    """
    handled = set()
    for method in cls.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(method):
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign) else []
            )
            for target in targets:
                if not (isinstance(target, ast.Attribute) and target.attr == 'queryset'):
                    continue
                sub = target.value
                if (isinstance(sub, ast.Subscript)
                        and isinstance(sub.slice, ast.Constant)
                        and isinstance(sub.slice.value, str)):
                    handled.add(sub.slice.value)
    return handled


def _check_model_form_meta_fields(tree, relpath, resolve_model):
    """Rule 2."""
    findings = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        meta = _meta_of(cls)
        if meta is None or not _looks_like_model_form(cls):
            continue
        meta_values = _assignments(meta)
        model_node = meta_values.get('model')
        if not isinstance(model_node, (ast.Name, ast.Attribute)):
            continue
        model_name = (
            model_node.attr if isinstance(model_node, ast.Attribute) else model_node.id
        )
        model = resolve_model(model_name, relpath)
        if model is None:
            continue

        fields_node = meta_values.get('fields')
        if fields_node is None:
            continue
        if (isinstance(fields_node, ast.Constant) and fields_node.value == '__all__'):
            candidates = [f.name for f in model._meta.get_fields() if hasattr(f, 'formfield')]
        else:
            candidates = _literal_names(fields_node)
            if not candidates:
                continue
        excluded = set(_literal_names(meta_values.get('exclude', ast.Constant(None))))
        declared = set(_assignments(cls))
        handled = _fields_handled_in_init(cls)

        for name in candidates:
            if name in excluded or name in declared or name in handled:
                continue
            try:
                field = model._meta.get_field(name)
            except Exception:
                continue
            if not (field.is_relation and field.related_model is not None):
                continue
            if not getattr(field, 'editable', False):
                continue
            if not _manager_is_scoped(field.related_model):
                continue
            findings.append(Finding(
                W002, relpath, (fields_node.lineno if fields_node else cls.lineno),
                cls.name,
                f'Meta.fields exposes {model.__name__}.{name} -> '
                f'{field.related_model._meta.label}',
                'ModelFormMetaclass calls ForeignKey.formfield() at import, which '
                'resolves the scoped default manager with no request in scope. '
                'Declare the field on the form, or set '
                f'self.fields[{name!r}].queryset in __init__.',
            ))
    return findings


def _manager_is_scoped(model):
    from core.tenancy import SchoolScopedManagerMixin
    try:
        return isinstance(model._meta.default_manager, SchoolScopedManagerMixin)
    except Exception:
        return False


def _make_model_resolver():
    """Resolve a model by its class name, preferring the file's own app."""
    from django.apps import apps as django_apps

    by_name = {}
    for model in django_apps.get_models():
        by_name.setdefault(model.__name__, []).append(model)

    def resolve(name, relpath):
        matches = by_name.get(name, [])
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        parts = Path(relpath).parts
        app_label = parts[1] if len(parts) > 1 else None
        for model in matches:
            if model._meta.app_label == app_label:
                return model
        return None

    return resolve


def _suppressed(source_lines, lineno):
    if 0 < lineno <= len(source_lines):
        return SUPPRESSION in source_lines[lineno - 1]
    return False


def collect_findings():
    resolve_model = _make_model_resolver()
    findings = []
    for path in _iter_python_files():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            print(f'{_rel(path)}: could not parse: {exc}', file=sys.stderr)
            continue
        lines = source.splitlines()
        relpath = _rel(path)
        found = (
            _check_class_body_querysets(tree, relpath)
            + _check_model_form_meta_fields(tree, relpath, resolve_model)
        )
        findings.extend(f for f in found if not _suppressed(lines, f.lineno))
    findings.sort(key=lambda f: (f.path, f.lineno, f.code))
    return findings


def _read_baseline():
    if not BASELINE_PATH.exists():
        return set()
    return {
        line.strip() for line in BASELINE_PATH.read_text().splitlines()
        if line.strip() and not line.startswith('#')
    }


def _write_baseline(findings):
    header = (
        '# Known import-time queryset sites, recorded so the lint can be\n'
        '# enforced against NEW ones while phase 3 converts these.\n'
        '#\n'
        '# This is a ratchet: removing a site from the code without removing it\n'
        "# here also fails the build, so the file cannot rot. Regenerate with\n"
        '#   python -m core.tenancy_lint --update-baseline\n'
        '# Never add a line by hand.\n'
    )
    body = '\n'.join(sorted(f.key for f in findings))
    BASELINE_PATH.write_text(header + body + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--update-baseline', action='store_true',
        help='rewrite the baseline from the current tree, then exit 0',
    )
    args = parser.parse_args(argv)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    sys.path.insert(0, str(REPO_ROOT))
    import django
    django.setup()

    findings = collect_findings()

    if args.update_baseline:
        _write_baseline(findings)
        print(f'Baseline rewritten: {len(findings)} known sites.')
        return 0

    baseline = _read_baseline()
    current = {f.key: f for f in findings}

    new = [f for key, f in current.items() if key not in baseline]
    stale = sorted(baseline - set(current))

    for finding in new:
        print(finding.render())
        print()

    if stale:
        print('Fixed sites still listed in the baseline — remove them with '
              '`python -m core.tenancy_lint --update-baseline`:')
        for key in stale:
            print(f'  {key}')
        print()

    if new or stale:
        print(
            f'FAIL: {len(new)} new import-time queryset site(s), '
            f'{len(stale)} stale baseline entr(y/ies). '
            f'{len(baseline)} known site(s) remain from phase 3.'
        )
        return 1

    print(
        f'OK: no new import-time querysets. '
        f'{len(baseline)} known site(s) remain for phase 3 to convert.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
