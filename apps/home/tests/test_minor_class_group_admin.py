"""
Tests for Подгруппы — the minor class groups managed in the admin panel.

Subgroups live in their own admin section, separate from regular classes, but
share the ClassGroup table: they can be enrolled into and can carry subject
offerings exactly like a whole class.
"""

import pytest
from django.urls import reverse

from apps.home.models import (
    ClassGroup, ClassGroupCollection, Enrollment, MinorClassGroup, SubjectOffering,
)
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, MinorClassGroupFactory,
    SubjectOfferingFactory, UserFactory,
)


@pytest.fixture
def superuser(db):
    return UserFactory(is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(client, superuser):
    # Logging in through the view: the user_logged_in signal posts a message,
    # which needs the middleware that client.login() bypasses.
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


# ── The proxy model ──

def test_manager_only_sees_minor_groups(major_a, subgroup):
    assert list(MinorClassGroup.objects.all()) == [subgroup]
    assert set(ClassGroup.objects.values_list('id', flat=True)) == {major_a.id, subgroup.id}


def test_saving_a_subgroup_forces_the_minor_category(academic_year):
    group = MinorClassGroup(academic_year=academic_year, letter='Шахматы')
    group.category = ClassGroup.MAJOR_CHOICE
    group.save()

    assert ClassGroup.objects.get(pk=group.pk).category == ClassGroup.MINOR_CHOICE


def test_creating_through_the_manager_forces_the_minor_category(academic_year):
    group = MinorClassGroup.objects.create(academic_year=academic_year, letter='Хор')

    assert group.is_minor


def test_subgroup_without_a_grade_level_is_named_by_its_letter(subgroup):
    assert subgroup.short_name == 'English Advanced'
    assert str(subgroup) == f'English Advanced ({subgroup.academic_year})'


def test_class_keeps_its_grade_prefixed_name(major_a):
    assert major_a.short_name == f'{major_a.grade_level}A'


# ── Admin CRUD ──

def test_subgroup_changelist_lists_only_subgroups(admin_client, major_a, subgroup):
    response = admin_client.get(reverse('admin:home_minorclassgroup_changelist'))

    assert response.status_code == 200
    listed = response.context['cl'].queryset
    assert list(listed) == [subgroup]


def test_class_changelist_leaves_out_subgroups(admin_client, major_a, subgroup):
    response = admin_client.get(reverse('admin:home_classgroup_changelist'))

    assert list(response.context['cl'].queryset) == [major_a]


def test_admin_can_create_a_subgroup(admin_client, academic_year):
    response = admin_client.post(
        reverse('admin:home_minorclassgroup_add'),
        {
            'letter': 'Робототехника',
            'grade_level': '',
            'academic_year': academic_year.id,
            'enrollments-TOTAL_FORMS': '0',
            'enrollments-INITIAL_FORMS': '0',
        },
    )

    assert response.status_code == 302
    created = MinorClassGroup.objects.get(letter='Робототехника')
    assert created.category == ClassGroup.MINOR_CHOICE
    assert created.grade_level is None


def test_admin_can_rename_a_subgroup(admin_client, subgroup):
    response = admin_client.post(
        reverse('admin:home_minorclassgroup_change', args=[subgroup.id]),
        {
            'letter': 'English Basic',
            'grade_level': '',
            'academic_year': subgroup.academic_year_id,
            'enrollments-TOTAL_FORMS': '0',
            'enrollments-INITIAL_FORMS': '0',
        },
    )

    assert response.status_code == 302
    subgroup.refresh_from_db()
    assert subgroup.letter == 'English Basic'
    assert subgroup.category == ClassGroup.MINOR_CHOICE


def test_admin_can_delete_a_subgroup(admin_client, subgroup):
    response = admin_client.post(
        reverse('admin:home_minorclassgroup_delete', args=[subgroup.id]),
        {'post': 'yes'},
    )

    assert response.status_code == 302
    assert not ClassGroup.objects.filter(pk=subgroup.id).exists()


def test_class_form_keeps_its_own_fields(admin_client, major_a):
    response = admin_client.get(
        reverse('admin:home_classgroup_change', args=[major_a.id])
    )

    assert response.status_code == 200
    assert set(response.context['adminform'].form.fields) == {
        'grade_level', 'letter', 'academic_year', 'minor_groups',
    }


def test_a_subgroup_cannot_be_edited_from_the_class_section(admin_client, subgroup):
    response = admin_client.get(
        reverse('admin:home_classgroup_change', args=[subgroup.id])
    )

    assert response.status_code == 302  # redirect to the admin index, "not found"


# ── Enrollment ──

def test_students_can_be_enrolled_into_a_subgroup_from_its_admin_page(
    admin_client, subgroup, student, major_a
):
    Enrollment.enroll_student(student, major_a)

    response = admin_client.post(
        reverse('admin:home_minorclassgroup_change', args=[subgroup.id]),
        {
            'letter': subgroup.letter,
            'grade_level': '',
            'academic_year': subgroup.academic_year_id,
            'enrollments-TOTAL_FORMS': '1',
            'enrollments-INITIAL_FORMS': '0',
            'enrollments-0-student': student.id,
            'enrollments-0-status': 'active',
            'enrollments-0-start_date': '',
            'enrollments-0-end_date': '',
        },
    )

    assert response.status_code == 302
    assert Enrollment.objects.filter(
        student=student, class_group=subgroup, status='active'
    ).exists()
    assert student.get_current_class_group() == major_a


def test_enrollment_admin_offers_subgroups_in_the_class_dropdown(admin_client, major_a, subgroup):
    response = admin_client.get(reverse('admin:home_enrollment_add'))

    field = response.context['adminform'].form.fields['class_group']
    assert {group.id for group in field.queryset} == {major_a.id, subgroup.id}
    assert field.label_from_instance(subgroup) == (
        f'English Advanced — подгруппа ({subgroup.academic_year})'
    )
    assert field.label_from_instance(major_a).endswith(f'— класс ({major_a.academic_year})')


def test_enrollment_changelist_can_be_filtered_to_subgroups(
    admin_client, student, subgroup, major_a
):
    Enrollment.enroll_student(student, major_a)
    Enrollment.enroll_student(student, subgroup)

    response = admin_client.get(
        reverse('admin:home_enrollment_changelist'),
        {'class_group__category__exact': ClassGroup.MINOR_CHOICE},
    )

    listed = response.context['cl'].queryset
    assert [enrollment.class_group_id for enrollment in listed] == [subgroup.id]


def test_bulk_enroll_page_offers_classes_and_subgroups(
    admin_client, student, major_a, subgroup
):
    session = admin_client.session
    session['bulk_enroll_students'] = [student.id]
    session.save()

    response = admin_client.get(reverse('admin_bulk_enroll_form'))

    assert response.status_code == 200
    assert response.context['major_groups'] == [major_a]
    assert response.context['minor_groups'] == [subgroup]


def test_bulk_enroll_into_a_subgroup_keeps_the_class(
    admin_client, student, major_a, subgroup
):
    Enrollment.enroll_student(student, major_a)
    session = admin_client.session
    session['bulk_enroll_students'] = [student.id]
    session.save()

    response = admin_client.post(
        reverse('admin_bulk_enroll_form'),
        {'students': [student.id], 'class_group': subgroup.id},
    )

    assert response.status_code == 302
    assert set(
        Enrollment.objects.filter(student=student, status='active')
        .values_list('class_group_id', flat=True)
    ) == {major_a.id, subgroup.id}


def test_enrollment_api_can_be_filtered_by_category(
    authenticated_client, admin_user, student, major_a, subgroup
):
    Enrollment.enroll_student(student, major_a)
    Enrollment.enroll_student(student, subgroup)
    client = authenticated_client(admin_user)

    response = client.get(
        reverse('home-api:enrollment-list'), {'category': ClassGroup.MINOR_CHOICE}
    )

    assert [row['class_group']['id'] for row in response.data['results']] == [subgroup.id]


# ── Constellations: binding подгруппы to a class ──

def post_class_form(admin_client, class_group, minor_ids):
    """Submit the class change form with the given subgroup selection."""
    return admin_client.post(
        reverse('admin:home_classgroup_change', args=[class_group.id]),
        {
            'letter': class_group.letter,
            'grade_level': class_group.grade_level_id or '',
            'academic_year': class_group.academic_year_id or '',
            'minor_groups': [str(pk) for pk in minor_ids],
            'enrollments-TOTAL_FORMS': '0',
            'enrollments-INITIAL_FORMS': '0',
        },
    )


@pytest.fixture
def other_subgroup(academic_year):
    return MinorClassGroupFactory(academic_year=academic_year, letter='Шахматы')


def test_the_subgroup_section_sits_below_the_enrollment_section(admin_client, major_a):
    response = admin_client.get(
        reverse('admin:home_classgroup_change', args=[major_a.id])
    )
    page = response.content.decode()

    assert page.index('Зачисления') < page.index('<h2>Подгруппы</h2>')


def test_only_subgroups_of_the_same_year_are_offered(admin_client, major_a, subgroup):
    next_year = AcademicYearFactory(is_active=False, year='2030/2031')
    MinorClassGroupFactory(academic_year=next_year, letter='Другой год')

    response = admin_client.get(
        reverse('admin:home_classgroup_change', args=[major_a.id])
    )

    field = response.context['adminform'].form.fields['minor_groups']
    assert list(field.queryset) == [subgroup]


def test_binding_a_subgroup_creates_the_constellation(admin_client, major_a, subgroup):
    assert not ClassGroupCollection.objects.exists()

    response = post_class_form(admin_client, major_a, [subgroup.id])

    assert response.status_code == 302
    collection = ClassGroupCollection.objects.get()
    assert collection.major == major_a
    assert list(collection.minor_groups.all()) == [subgroup]


def test_saving_without_a_selection_creates_no_constellation(admin_client, major_a):
    response = post_class_form(admin_client, major_a, [])

    assert response.status_code == 302
    assert not ClassGroupCollection.objects.exists()


def test_the_form_comes_back_with_the_bound_subgroups_selected(
    admin_client, major_a, subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])

    response = admin_client.get(
        reverse('admin:home_classgroup_change', args=[major_a.id])
    )

    assert response.context['adminform'].form['minor_groups'].value() == [subgroup.id]


def test_one_subgroup_can_be_bound_to_several_classes(
    admin_client, major_a, major_b, subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])
    post_class_form(admin_client, major_b, [subgroup.id])

    assert {c.major for c in subgroup.collections.all()} == {major_a, major_b}
    assert ClassGroupCollection.objects.count() == 2


def test_binding_a_second_subgroup_reuses_the_constellation(
    admin_client, major_a, subgroup, other_subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])
    post_class_form(admin_client, major_a, [subgroup.id, other_subgroup.id])

    collection = ClassGroupCollection.objects.get()
    assert set(collection.minor_groups.all()) == {subgroup, other_subgroup}


def test_removing_one_of_two_subgroups_keeps_the_constellation(
    admin_client, major_a, subgroup, other_subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id, other_subgroup.id])

    post_class_form(admin_client, major_a, [other_subgroup.id])

    collection = ClassGroupCollection.objects.get()
    assert list(collection.minor_groups.all()) == [other_subgroup]


def test_removing_the_last_subgroup_leaves_the_constellation_in_place(
    admin_client, major_a, subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])

    post_class_form(admin_client, major_a, [])

    collection = ClassGroupCollection.objects.get()
    assert collection.major == major_a
    assert not collection.minor_groups.exists()
    assert ClassGroup.objects.filter(pk=subgroup.id).exists()  # the subgroup itself stays


def test_subgroups_from_another_year_are_rejected(admin_client, major_a):
    next_year = AcademicYearFactory(is_active=False, year='2030/2031')
    stranger = MinorClassGroupFactory(academic_year=next_year, letter='Другой год')

    response = post_class_form(admin_client, major_a, [stranger.id])

    assert response.status_code == 200  # redisplayed with the error
    assert 'minor_groups' in response.context['adminform'].form.errors
    assert not ClassGroupCollection.objects.exists()


def test_deleting_the_class_takes_its_constellation_with_it(
    admin_client, major_a, subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])

    major_a.delete()

    assert not ClassGroupCollection.objects.exists()
    assert ClassGroup.objects.filter(pk=subgroup.id).exists()


def test_deleting_a_subgroup_only_unbinds_it(
    admin_client, major_a, major_b, subgroup, other_subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id, other_subgroup.id])
    post_class_form(admin_client, major_b, [subgroup.id])

    admin_client.post(
        reverse('admin:home_minorclassgroup_delete', args=[subgroup.id]),
        {'post': 'yes'},
    )

    # 7A keeps its second subgroup; 7B's constellation stays, now empty.
    by_class = {c.major: list(c.minor_groups.all()) for c in ClassGroupCollection.objects.all()}
    assert by_class == {major_a: [other_subgroup], major_b: []}


def test_bulk_deleting_subgroups_leaves_the_constellations(
    admin_client, major_a, subgroup, other_subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id, other_subgroup.id])

    admin_client.post(
        reverse('admin:home_minorclassgroup_changelist'),
        {
            'action': 'delete_selected',
            '_selected_action': [str(subgroup.id), str(other_subgroup.id)],
            'post': 'yes',
        },
    )

    assert not MinorClassGroup.objects.exists()
    collection = ClassGroupCollection.objects.get()
    assert collection.major == major_a
    assert not collection.minor_groups.exists()


def test_changelists_show_both_sides_of_the_constellation(
    admin_client, major_a, subgroup
):
    post_class_form(admin_client, major_a, [subgroup.id])

    classes = admin_client.get(reverse('admin:home_classgroup_changelist'))
    subgroups = admin_client.get(reverse('admin:home_minorclassgroup_changelist'))

    assert 'English Advanced' in classes.content.decode()
    assert major_a.short_name in subgroups.content.decode()


# ── Subject offerings ──

def test_an_offering_can_be_created_for_a_subgroup(admin_client, subject, subgroup):
    response = admin_client.post(
        reverse('admin:home_subjectoffering_add'),
        {
            'subject': subject.id,
            'class_group': subgroup.id,
            'max_points': '100',
            'grading_strategy': 'average',
            'teaching_assignments-TOTAL_FORMS': '0',
            'teaching_assignments-INITIAL_FORMS': '0',
            'lessons-TOTAL_FORMS': '0',
            'lessons-INITIAL_FORMS': '0',
        },
    )

    assert response.status_code == 302
    offering = SubjectOffering.objects.get(subject=subject)
    assert offering.class_group_id == subgroup.id


def test_offering_students_come_from_the_subgroup_enrollment(subject, subgroup, student):
    offering = SubjectOfferingFactory(subject=subject, class_group=subgroup)
    Enrollment.enroll_student(student, subgroup)

    assert [e.student for e in offering.get_students()] == [student]
