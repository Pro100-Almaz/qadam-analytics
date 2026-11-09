"""
Enrolling from the class / subgroup admin page: a rejected row is shown back
to the admin as a form error, never a 500 (IntegrityError / ValidationError
raised from `Enrollment.save()`).
"""

import pytest
from django.urls import reverse

from apps.home.models import Enrollment
from core.factories import ClassGroupFactory, MinorClassGroupFactory, UserFactory


@pytest.fixture
def school(db):
    from core.factories import SchoolFactory
    return SchoolFactory()


@pytest.fixture
def admin_client(client, school):
    superuser = UserFactory(is_staff=True, is_superuser=True, school=school)
    client.post(
        reverse('admin:login'),
        {'username': superuser.username, 'password': 'testpass123', 'next': '/admin/'},
    )
    return client


@pytest.fixture
def major_a(academic_year):
    return ClassGroupFactory(academic_year=academic_year, letter='A')


@pytest.fixture
def major_b(academic_year, major_a):
    return ClassGroupFactory(
        academic_year=academic_year, grade_level=major_a.grade_level, letter='B',
    )


@pytest.fixture
def subgroup(academic_year):
    return MinorClassGroupFactory(academic_year=academic_year, letter='English Advanced')


def post_enrollments(admin_client, group, rows, initial=()):
    """Submit the group's change page with `initial` existing and `rows` new enrollments."""
    url_name = 'admin:home_minorclassgroup_change' if group.is_minor else 'admin:home_classgroup_change'
    data = {
        'letter': group.letter,
        'grade_level': group.grade_level_id or '',
        'academic_year': group.academic_year_id or '',
        'enrollments-TOTAL_FORMS': str(len(initial) + len(rows)),
        'enrollments-INITIAL_FORMS': str(len(initial)),
    }
    forms = [(e.student_id, e.status, e.pk) for e in initial] + [(s.id, st, '') for s, st in rows]
    for i, (student_id, status, pk) in enumerate(forms):
        data.update({
            f'enrollments-{i}-id': pk,
            f'enrollments-{i}-class_group': group.id,
            f'enrollments-{i}-student': student_id,
            f'enrollments-{i}-status': status,
            f'enrollments-{i}-start_date': '',
            f'enrollments-{i}-end_date': '',
        })
    return admin_client.post(reverse(url_name, args=[group.id]), data)


def inline_errors(response):
    return [
        msg for form in response.context['inline_admin_formsets'][0].formset.forms
        for msg in form.errors.get('student', [])
    ]


def test_re_enrolling_an_active_student_into_a_subgroup_warns_instead_of_500(
    admin_client, subgroup, student
):
    Enrollment.enroll_student(student, subgroup)

    response = post_enrollments(admin_client, subgroup, [(student, 'active')])

    assert response.status_code == 200
    assert inline_errors(response) == ['Ученик уже активно зачислен в эту группу.']
    assert Enrollment.objects.filter(student=student, class_group=subgroup).count() == 1


def test_re_enrolling_an_active_student_into_a_class_warns_instead_of_500(
    admin_client, major_a, student
):
    Enrollment.enroll_student(student, major_a)

    response = post_enrollments(admin_client, major_a, [(student, 'active')])

    assert response.status_code == 200
    assert inline_errors(response) == ['Ученик уже активно зачислен в эту группу.']


def test_same_student_on_two_new_rows_warns(admin_client, subgroup, student):
    response = post_enrollments(
        admin_client, subgroup, [(student, 'active'), (student, 'active')],
    )

    assert response.status_code == 200
    assert inline_errors(response) == ['Этот ученик уже указан выше как активный.']
    assert not Enrollment.objects.filter(class_group=subgroup).exists()


def test_second_active_major_class_warns_instead_of_500(
    admin_client, major_a, major_b, student
):
    Enrollment.enroll_student(student, major_a)

    response = post_enrollments(admin_client, major_b, [(student, 'active')])

    assert response.status_code == 200
    assert len(inline_errors(response)) == 1
    assert not Enrollment.objects.filter(student=student, class_group=major_b).exists()


def test_re_enrolling_is_allowed_once_the_old_row_leaves_active(
    admin_client, subgroup, student
):
    existing = Enrollment.objects.create(student=student, class_group=subgroup)
    existing.status = 'withdrawn'

    response = post_enrollments(
        admin_client, subgroup, [(student, 'active')], initial=[existing],
    )

    assert response.status_code == 302
    assert Enrollment.objects.filter(
        student=student, class_group=subgroup, status='active',
    ).count() == 1
