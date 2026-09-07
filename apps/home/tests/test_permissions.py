import pytest
from django.urls import reverse
from rest_framework import status

from core.factories import (
    StudentFactory, TeacherFactory, ParentFactory, SupervisorFactory,
    AdminUserFactory, AcademicYearFactory, ClassGroupFactory,
    SubjectFactory, SubjectOfferingFactory, TeachingAssignmentFactory,
    EnrollmentFactory, LessonFactory, TopicFactory,
)


@pytest.mark.django_db
class TestStudentPermissionBoundaries:
    """Students must not access teacher/admin endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self, academic_year):
        self.academic_year = academic_year

    @pytest.mark.parametrize("url_name,method", [
        ("home-api:subject-create", "post"),
        ("auth-api:register", "post"),
        ("home-api:enrollment-list", "get"),
    ])
    def test_student_cannot_access_admin_endpoints(
        self, authenticated_client, student, url_name, method
    ):
        client = authenticated_client(student.user)
        url = reverse(url_name)
        response = getattr(client, method)(url, format='multipart')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_cannot_update_other_student(
        self, authenticated_client, student
    ):
        other_student = StudentFactory(academic_year=self.academic_year)
        client = authenticated_client(student.user)
        url = reverse('home-api:student-update', kwargs={'pk': other_student.pk})
        response = client.patch(url, {'first_name': 'Hacked'}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_cannot_create_lesson(
        self, authenticated_client, student, offering
    ):
        client = authenticated_client(student.user)
        url = reverse('lesson-api:lesson-list-create')
        response = client.post(url, {
            'offering': offering.pk,
            'title': 'Fake Lesson',
            'quarter': 1,
            'unit': 1,
        }, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_cannot_submit_grades(
        self, authenticated_client, student, lesson
    ):
        client = authenticated_client(student.user)
        url = reverse('lesson-api:grading', kwargs={'lesson_id': lesson.pk})
        response = client.post(url, {'grades': []}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestParentPermissionBoundaries:
    """Parents must not access teacher/admin endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self, academic_year):
        self.academic_year = academic_year

    @pytest.mark.parametrize("url_name,method", [
        ("home-api:subject-create", "post"),
        ("auth-api:register", "post"),
        ("home-api:enrollment-list", "get"),
    ])
    def test_parent_cannot_access_admin_endpoints(
        self, authenticated_client, parent, url_name, method
    ):
        client = authenticated_client(parent.user)
        url = reverse(url_name)
        response = getattr(client, method)(url, format='multipart')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_parent_cannot_create_lesson(
        self, authenticated_client, parent, offering
    ):
        client = authenticated_client(parent.user)
        url = reverse('lesson-api:lesson-list-create')
        response = client.post(url, {
            'offering': offering.pk,
            'title': 'Fake Lesson',
            'quarter': 1,
            'unit': 1,
        }, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestTeacherPermissionBoundaries:
    """Teachers have access to their own offerings but not admin actions."""

    @pytest.fixture(autouse=True)
    def setup(self, academic_year):
        self.academic_year = academic_year

    def test_teacher_cannot_register_users(
        self, authenticated_client, teacher
    ):
        client = authenticated_client(teacher.user)
        response = client.post(
            reverse('auth-api:register'),
            {
                'first_name': 'New',
                'last_name': 'User',
                'email': 'new@test.kz',
                'password1': 'testpass123',
                'password2': 'testpass123',
                'role': 'Student',
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestHorizontalAccessControl:
    """Users cannot access other users' data."""

    @pytest.fixture(autouse=True)
    def setup(self, academic_year):
        self.academic_year = academic_year

    def test_parent_cannot_see_other_parents_children(
        self, authenticated_client
    ):
        parent_a = ParentFactory()
        parent_b = ParentFactory()
        child_b = StudentFactory(academic_year=self.academic_year)
        parent_b.students.add(child_b)

        client = authenticated_client(parent_a.user)
        url = reverse('home-api:parent-child-detail', kwargs={'student_pk': child_b.pk})
        response = client.get(url)
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]

    def test_teacher_cannot_grade_other_teachers_offering(
        self, authenticated_client
    ):
        class_group = ClassGroupFactory(academic_year=self.academic_year)
        offering = SubjectOfferingFactory(
            class_group=class_group,
            academic_year=self.academic_year,
        )
        other_teacher = TeacherFactory()
        TeachingAssignmentFactory(teacher=other_teacher, offering=offering)
        lesson = LessonFactory(offering=offering)

        my_teacher = TeacherFactory()
        client = authenticated_client(my_teacher.user)
        url = reverse('lesson-api:grading', kwargs={'lesson_id': lesson.pk})
        response = client.post(url, {'grades': []}, format='json')
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]

    def test_student_cannot_see_other_class_student_detail(
        self, authenticated_client
    ):
        cg_a = ClassGroupFactory(academic_year=self.academic_year)
        cg_b = ClassGroupFactory(academic_year=self.academic_year)
        student_a = StudentFactory(academic_year=self.academic_year)
        student_b = StudentFactory(academic_year=self.academic_year)
        EnrollmentFactory(student=student_a, class_group=cg_a, academic_year=self.academic_year)
        EnrollmentFactory(student=student_b, class_group=cg_b, academic_year=self.academic_year)

        client = authenticated_client(student_a.user)
        url = reverse('home-api:student-detail', kwargs={'pk': student_b.pk})
        response = client.get(url)
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]


@pytest.mark.django_db
class TestAdminAndSupervisorAccess:
    """Admins and supervisors can access everything."""

    @pytest.fixture(autouse=True)
    def setup(self, academic_year):
        self.academic_year = academic_year

    def test_admin_can_list_enrollments(self, authenticated_client, admin_user):
        client = authenticated_client(admin_user)
        response = client.get(reverse('home-api:enrollment-list'))
        assert response.status_code == status.HTTP_200_OK

    def test_supervisor_can_list_enrollments(self, authenticated_client, supervisor):
        client = authenticated_client(supervisor.user)
        response = client.get(reverse('home-api:enrollment-list'))
        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_create_subject(self, authenticated_client, admin_user):
        client = authenticated_client(admin_user)
        response = client.post(reverse('home-api:subject-create'), {
            'name': 'New Subject',
            'language_group': 'kaz',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
