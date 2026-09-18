"""The import-time queryset lint must actually fail things.

A lint that cannot fire is worse than no lint: it reads as coverage while the
sites it was meant to stop accumulate behind it. These build each shape the two
rules exist for and assert the right code comes back — and, as importantly,
assert the shapes that must NOT fire, because a false positive on a build gate
is what gets a lint suppressed and then deleted.
"""

import ast

import pytest

from core import tenancy_lint
from core.tenancy_lint import (
    W001, W002, _check_class_body_querysets, _check_model_form_meta_fields,
    _make_model_resolver, collect_findings,
)


@pytest.fixture(scope='module')
def resolve_model():
    return _make_model_resolver()


def _rule1(source):
    return _check_class_body_querysets(ast.parse(source), 'apps/home/probe.py')


def _rule2(source, resolve_model, relpath='apps/home/probe.py'):
    return _check_model_form_meta_fields(ast.parse(source), relpath, resolve_model)


def _codes(findings):
    return sorted(f.code for f in findings)


# --------------------------------------------------------------- rule 1 ----

def test_serializer_field_queryset_is_flagged():
    assert _codes(_rule1(
        'class S(Serializer):\n'
        '    student = PrimaryKeyRelatedField(queryset=Student.objects.all())\n'
    )) == [W001]


def test_select_related_is_flagged_too():
    """`.select_related(...)` is a QuerySet just as much as `.all()` is."""
    assert _codes(_rule1(
        'class S(Serializer):\n'
        '    o = PrimaryKeyRelatedField(queryset=Offering.objects.select_related("subject"))\n'
    )) == [W001]


def test_passing_the_manager_is_the_fix_and_is_not_flagged():
    """DRF calls .all() on a Manager per request, re-entering the scope."""
    assert _rule1(
        'class S(Serializer):\n'
        '    student = PrimaryKeyRelatedField(queryset=Student.objects)\n'
    ) == []


def test_queryset_none_is_not_flagged():
    assert _rule1(
        'class F(ModelForm):\n'
        '    groups = ModelMultipleChoiceField(queryset=None)\n'
    ) == []


def test_generic_view_class_attribute_is_flagged():
    assert _codes(_rule1(
        'class V(ListAPIView):\n'
        '    queryset = Subject.objects.all()\n'
    )) == [W001]


def test_the_generic_view_hint_does_not_say_pass_the_manager():
    """GenericAPIView re-chains only a QuerySet, so a Manager breaks pagination."""
    hint = _rule1('class V(ListAPIView):\n    queryset = Subject.objects.all()\n')[0].hint
    assert 'get_queryset()' in hint
    assert 'Pass the Manager' not in hint


def test_a_queryset_inside_a_method_is_fine():
    """Methods run per request, inside the scope. That is the whole distinction."""
    assert _rule1(
        'class V(ListAPIView):\n'
        '    def get_queryset(self):\n'
        '        return Subject.objects.all()\n'
    ) == []


def test_the_unscoped_manager_is_not_flagged():
    """`unscoped` never applies the filter, so freezing it changes nothing."""
    assert _rule1(
        'class S(Serializer):\n'
        '    a = PrimaryKeyRelatedField(queryset=Achievement.unscoped.all())\n'
    ) == []


# --------------------------------------------------------------- rule 2 ----

def test_model_form_exposing_a_scoped_fk_is_flagged(resolve_model):
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        '        fields = ("grade_level", "letter", "academic_year")\n',
        resolve_model,
    )
    assert _codes(findings) == [W002]
    assert 'academic_year' in findings[0].detail


def test_a_shared_model_fk_is_not_flagged(resolve_model):
    """GradeLevel is shared (grades 1-11 are universal), so its manager is plain."""
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        '        fields = ("grade_level", "letter")\n',
        resolve_model,
    )
    assert findings == []


def test_a_fk_to_customuser_is_not_flagged(resolve_model):
    """CustomUser.objects stays unscoped so login works — nothing to bake."""
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = Student\n'
        '        fields = ("user",)\n',
        resolve_model,
    )
    assert findings == []


def test_declaring_the_field_exempts_it(resolve_model):
    """fields_for_model short-circuits on form_declared_fields before formfield()."""
    findings = _rule2(
        'class F(ModelForm):\n'
        '    academic_year = ModelChoiceField(queryset=None)\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        '        fields = ("academic_year",)\n',
        resolve_model,
    )
    assert findings == []


def test_setting_the_queryset_in_init_exempts_it(resolve_model):
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        '        fields = ("academic_year",)\n'
        '    def __init__(self, *a, **kw):\n'
        '        super().__init__(*a, **kw)\n'
        '        self.fields["academic_year"].queryset = AcademicYear.objects.all()\n',
        resolve_model,
    )
    assert findings == []


def test_fields_all_is_expanded(resolve_model):
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        "        fields = '__all__'\n",
        resolve_model,
    )
    assert _codes(findings) == [W002]


def test_exclude_is_honoured(resolve_model):
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        "        fields = '__all__'\n"
        "        exclude = ('academic_year',)\n",
        resolve_model,
    )
    assert findings == []


def test_many_to_many_is_covered(resolve_model):
    """fields_for_model walks opts.many_to_many too, and m2m formfields also
    resolve the default manager."""
    findings = _rule2(
        'class F(ModelForm):\n'
        '    class Meta:\n'
        '        model = Student\n'
        '        fields = ("subjects",)\n',
        resolve_model,
    )
    assert _codes(findings) == [W002]


def test_a_model_serializer_is_not_a_model_form(resolve_model):
    """DRF builds fields lazily on the instance — no import-time hazard."""
    findings = _rule2(
        'class S(ModelSerializer):\n'
        '    class Meta:\n'
        '        model = ClassGroup\n'
        '        fields = ("academic_year",)\n',
        resolve_model,
    )
    assert findings == []


# ------------------------------------------------------------- the tree ----

def test_the_tree_matches_its_baseline():
    """The ratchet. Fails on a new site, and on a fixed site left listed."""
    baseline = tenancy_lint._read_baseline()
    current = {f.key for f in collect_findings()}
    assert not (current - baseline), (
        f'New import-time queryset sites: {sorted(current - baseline)}'
    )
    assert not (baseline - current), (
        'Baselined sites that no longer exist — rerun the lint with '
        f'--update-baseline: {sorted(baseline - current)}'
    )


def test_the_baseline_is_not_empty():
    """Without this, a lint that stopped matching anything would look green."""
    assert len(tenancy_lint._read_baseline()) > 30


def test_the_known_crasher_is_covered():
    """apps/home/admin.py's MajorClassGroupForm.academic_year is the site that
    crashes django.setup() under 'enforce', before any system check can run."""
    keys = {f.key for f in collect_findings()}
    assert any(
        'MajorClassGroupForm' in k and 'academic_year' in k and W002 in k
        for k in keys
    )
