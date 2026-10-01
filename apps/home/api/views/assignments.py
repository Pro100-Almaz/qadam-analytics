"""
CRUD endpoints for subject assignments and the grades given for them.

A SubjectAssignment is a piece of graded work that belongs to a
SubjectOffering — "Math for 7A in 2025/2026" — and nothing else. It is not a
lesson and carries no topics or weights: a title, a category (an
AssignmentCategory an admin manages — lesson, exam, final, homework, …), a
maximum grade, the date it took place, and one SubjectGrade per student.

Category `homework` is the mirror of a lesson.Homework (spec 0005): creating one
here creates the Homework, and edits on either side reach the other
(apps/lesson/homework_sync.py). Deleting is one-way (spec 0007): a homework
assignment is removed by deleting its Homework, never from here. A draft (`is_active=False`) is visible only to
the offering's teachers and to admin roles.

Write access — assignments and grades alike:
- Only a teacher assigned to the offering (TeachingAssignment). An offering can
  carry several teachers, so the boundary is the offering rather than the
  person who typed the assignment in. Admin roles are deliberately *not*
  allowed to write; they read the whole school instead.
- Grades may only be given to students actively enrolled in the offering's own
  class group, for that offering's academic year.

Read access:
- Admin / Principal / Supervisor and Psychologist — everything, school-wide.
- Teacher        — the assignments and grades of every offering they teach,
                   plus, for grades, their own homeroom class across every
                   subject taught to it.
- Homeroom teacher — that homeroom reach has its own endpoints,
                   my-class/subject-assignments/ and
                   teachers/my-class/subject-grades/, each spanning every
                   subject their class is taught rather than only the ones they
                   teach — and, conversely, never their own work for the other
                   classes they teach.
- Student        — their own grades, and the published assignments of the
                   classes they are enrolled in.
- Parent         — the same, for their children.
Nobody else sees any of it.
"""

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Student, Teacher
from apps.home.models import (
    AssignmentCategory, Enrollment, SubjectAssignment, SubjectGrade,
    SubjectOffering, TeachingAssignment,
)
from core.error_messages import (
    HOMEWORK_ASSIGNMENT_DELETE, NO_PERMISSION, OWN_OFFERINGS_ONLY,
)
from core.permissions import (
    IsTeacherRole,
    is_admin_role,
    is_teacher_role,
    teacher_homeroom_class_group_ids,
)

from apps.home.api.serializers import (
    AssignmentCategorySerializer,
    SubjectAssignmentCreateSerializer,
    SubjectAssignmentSerializer,
    SubjectAssignmentWithGradesSerializer,
    SubjectAssignmentWriteSerializer,
    SubjectGradeSerializer,
    SubjectGradeWriteSerializer,
)


class SubjectAssignmentPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


ASSIGNMENT_SELECT_RELATED = (
    'category', 'offering', 'offering__subject',
    'offering__class_group', 'offering__class_group__grade_level',
    'offering__class_group__academic_year',
)


# ── Queryset scoping ──

def enrolled_offering_query(students, prefix=''):
    """
    Q matching rows whose offering is taught to a class one of `students` is
    actively enrolled in.

    The academic year needs no clause of its own: a class group belongs to
    exactly one year, and an offering's year is its class group's, so pinning
    the class group already pins the year.

    Returns None when there is no active enrollment at all: an empty Q would
    filter on nothing and hand back the whole table, so callers turn None into
    an empty queryset instead.
    """
    class_group_ids = list(
        Enrollment.objects.filter(
            student__in=students, status='active',
        ).values_list('class_group_id', flat=True).distinct()
    )
    if not class_group_ids:
        return None
    return Q(**{f'{prefix}offering__class_group_id__in': class_group_ids})


def teacher_offering_ids(teacher):
    """Ids of every offering this teacher is assigned to, in any role."""
    return TeachingAssignment.objects.filter(
        teacher=teacher,
    ).values_list('offering_id', flat=True)


def assignment_queryset(user):
    """Assignments visible to the requesting user — see the module docstring."""
    qs = SubjectAssignment.objects.select_related(*ASSIGNMENT_SELECT_RELATED)

    if is_admin_role(user) or user.is_psychologist():
        return qs

    if is_teacher_role(user):
        teacher = Teacher.objects.filter(user=user).first()
        if teacher is None:
            return qs.none()
        return qs.filter(offering_id__in=teacher_offering_ids(teacher))

    if user.is_student():
        student = Student.objects.filter(user=user).first()
        if student is None:
            return qs.none()
        query = enrolled_offering_query([student])
        return qs.filter(query, is_active=True) if query else qs.none()

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        query = enrolled_offering_query(parent.students.all())
        return qs.filter(query, is_active=True) if query else qs.none()

    return qs.none()


def grade_queryset(user):
    """
    Grades visible to the requesting user.

    Students see their own rows, parents their children's, teachers the
    offerings they teach plus anything belonging to their homeroom class, and
    psychologists / admin roles see everything.
    """
    qs = SubjectGrade.objects.select_related(
        'student', 'student__user',
        *(f'assignment__{part}' for part in ASSIGNMENT_SELECT_RELATED),
    )

    if is_admin_role(user) or user.is_psychologist():
        return qs

    if is_teacher_role(user):
        teacher = Teacher.objects.filter(user=user).first()
        if teacher is None:
            return qs.none()
        return qs.filter(
            Q(assignment__offering_id__in=teacher_offering_ids(teacher))
            | Q(
                student__enrollments__class_group_id__in=(
                    teacher_homeroom_class_group_ids(teacher)
                ),
                student__enrollments__status='active',
                assignment__is_active=True,
            )
        ).distinct()

    if user.is_student():
        return qs.filter(student__user=user, assignment__is_active=True)

    if user.is_parent():
        parent = Parent.objects.filter(user=user).first()
        if parent is None:
            return qs.none()
        return qs.filter(
            student__in=parent.students.all(), assignment__is_active=True,
        )

    return qs.none()


def homeroom_assignment_queryset(user):
    """
    Every assignment set to the caller's own homeroom class, across all subjects
    taught to it — not only the subjects the caller teaches, and never the
    caller's own assignments for their other classes.

    Empty for anyone without a homeroom assignment in the active academic year,
    admin roles included: they reach the same rows through GET
    subject-assignments/?class_group=<id>.
    """
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return SubjectAssignment.objects.none()

    class_group_ids = teacher_homeroom_class_group_ids(teacher)
    if not class_group_ids:
        return SubjectAssignment.objects.none()

    return SubjectAssignment.objects.select_related(
        *ASSIGNMENT_SELECT_RELATED,
    ).filter(offering__class_group_id__in=class_group_ids, is_active=True)


def homeroom_grade_queryset(user):
    """
    Every grade of the students in the caller's own homeroom class, across all
    subjects taught to it — not only the subjects the caller teaches.

    Empty for anyone without a homeroom assignment in the active academic year,
    admin roles included: they reach the same rows through GET subject-grades/.
    """
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return SubjectGrade.objects.none()

    class_group_ids = teacher_homeroom_class_group_ids(teacher)
    if not class_group_ids:
        return SubjectGrade.objects.none()

    return SubjectGrade.objects.select_related(
        'student', 'student__user',
        *(f'assignment__{part}' for part in ASSIGNMENT_SELECT_RELATED),
    ).filter(
        student__enrollments__class_group_id__in=class_group_ids,
        student__enrollments__status='active',
        assignment__is_active=True,
    ).distinct()


# ── Write permissions ──

def teacher_assignment_for(user, offering):
    """The requesting user's own TeachingAssignment for an offering, or None."""
    teacher = Teacher.objects.filter(user=user).first()
    if teacher is None:
        return None
    return TeachingAssignment.objects.filter(
        offering=offering, teacher=teacher,
    ).first()


def can_manage_assignment(user, assignment):
    """
    Whether the user may edit, delete or grade this assignment.

    An assignment belongs to its offering rather than to one person: any
    teacher of that offering — primary, assistant, substitute — may work on it,
    including one a colleague created. Homeroom teachers who do not teach the
    subject are not included: their homeroom reach is read-only.
    """
    return teacher_assignment_for(user, assignment.offering) is not None


# ── Filters ──

def apply_offering_filters(qs, params, prefix=''):
    """
    Narrow any queryset that reaches a SubjectOffering by `{prefix}offering`.

    `prefix` is '' for rows holding the offering directly (assignments, quarter
    grades) and 'assignment__' for subject grades, which reach it through their
    assignment. Shared with the quarter-grade views.
    """
    if params.get('offering'):
        qs = qs.filter(**{f'{prefix}offering_id': params['offering']})
    if params.get('subject'):
        qs = qs.filter(**{f'{prefix}offering__subject_id': params['subject']})
    if params.get('class_group'):
        qs = qs.filter(**{f'{prefix}offering__class_group_id': params['class_group']})
    if params.get('academic_year'):
        qs = qs.filter(**{f'{prefix}offering__class_group__academic_year_id': params['academic_year']})
    return qs


def _apply_assignment_filters(qs, params, prefix=''):
    """
    Offering filters plus `category` and the assignment's own `date`.

    The date is filtered either exactly (`date`) or as a closed range
    (`date_from` / `date_to`, either end optional) — enough to ask for one day,
    one week or one quarter without a second endpoint.
    """
    qs = apply_offering_filters(qs, params, prefix=prefix)
    if params.get('category'):
        qs = qs.filter(**{f'{prefix}category__code': params['category']})
    if params.get('date'):
        qs = qs.filter(**{f'{prefix}date': params['date']})
    if params.get('date_from'):
        qs = qs.filter(**{f'{prefix}date__gte': params['date_from']})
    if params.get('date_to'):
        qs = qs.filter(**{f'{prefix}date__lte': params['date_to']})
    return qs


OFFERING_FILTER_PARAMS = [
    OpenApiParameter('offering', int, description='Subject offering id.'),
    OpenApiParameter('subject', int, description='Subject id.'),
    OpenApiParameter('class_group', int, description='Class group id.'),
    OpenApiParameter('academic_year', int),
]

PAGE_PARAMS = [
    OpenApiParameter('page', int),
    OpenApiParameter('page_size', int),
]

# No `enum`: categories are rows an admin manages (spec 0005), so the valid
# codes are whatever GET assignment-categories/ returns today.
CATEGORY_PARAM = OpenApiParameter(
    'category', str,
    description='Assignment category code, from GET assignment-categories/ '
                '(lesson, exam, final, homework, …).',
)

DATE_PARAMS = [
    OpenApiParameter(
        'date', OpenApiTypes.DATE,
        description='Exact assignment date, YYYY-MM-DD.',
    ),
    OpenApiParameter(
        'date_from', OpenApiTypes.DATE,
        description='Assignments dated on or after this day, YYYY-MM-DD.',
    ),
    OpenApiParameter(
        'date_to', OpenApiTypes.DATE,
        description='Assignments dated on or before this day, YYYY-MM-DD.',
    ),
]

ASSIGNMENT_FILTER_PARAMS = (
    OFFERING_FILTER_PARAMS + [CATEGORY_PARAM] + DATE_PARAMS + PAGE_PARAMS
)


def _assignment_list_response(view, request, rows):
    """
    Filter, order and paginate an assignment queryset into a list response.

    Shared by the role-scoped list and the homeroom one so the two only ever
    differ in the queryset they start from — the payload, the filters and the
    ordering are the same by construction.
    """
    rows = _apply_assignment_filters(rows, request.query_params).order_by(
        '-date', '-created_at', '-id',
    )

    paginator = SubjectAssignmentPagination()
    page = paginator.paginate_queryset(rows, request, view=view)
    serializer = SubjectAssignmentSerializer(
        page, many=True, context={'request': request},
    )
    return paginator.get_paginated_response(serializer.data)


# ── Assignments ──

class SubjectAssignmentListCreateAPIView(APIView):
    """
    GET  subject-assignments/  — assignments the caller is allowed to see
    POST subject-assignments/  — create one in an offering the caller teaches
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherRole()]
        return [IsAuthenticated()]

    @extend_schema(
        responses=SubjectAssignmentSerializer(many=True),
        parameters=ASSIGNMENT_FILTER_PARAMS,
        description=(
            'Role-scoped list of subject assignments. Teachers get the '
            'offerings they teach and nothing else — a homeroom class they do '
            'not teach is read through GET my-class/subject-assignments/ '
            'instead. Students and parents get the classes they (or their '
            'children) are enrolled in, and admin roles and psychologists the '
            'whole school. Filter by `category` to separate ordinary work from '
            'exams and finals, and by `date` / `date_from` / `date_to` to pick '
            'a day or a range. Newest assignment date first.'
        ),
    )
    def get(self, request):
        return _assignment_list_response(
            self, request, assignment_queryset(request.user),
        )

    @extend_schema(
        request=SubjectAssignmentCreateSerializer,
        responses={201: SubjectAssignmentSerializer},
        description=(
            'Creates an assignment. The caller must be an assigned teacher of '
            'the target offering, otherwise the request is a 403.'
        ),
    )
    def post(self, request):
        serializer = SubjectAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        offering = data['offering']
        teaching_assignment = teacher_assignment_for(request.user, offering)
        if teaching_assignment is None:
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )

        if data['category'].code == AssignmentCategory.HOMEWORK:
            # A homework assignment is a Homework's mirror: create the Homework
            # on the caller's own teaching assignment and let it make the mirror.
            from apps.lesson.homework_sync import create_homework_with_assignment
            assignment = create_homework_with_assignment(
                offering=offering,
                teaching_assignment=teaching_assignment,
                title=data['title'],
                max_grade=data['max_grade'],
                date=data['date'],
                is_active=data['is_active'],
            )
        else:
            assignment = serializer.save()
        return Response(
            SubjectAssignmentSerializer(assignment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class SubjectAssignmentDetailAPIView(APIView):
    """
    GET    subject-assignments/<pk>/  — single assignment
    PATCH  subject-assignments/<pk>/  — change title / category / max_grade /
                                       date / is_active
    DELETE subject-assignments/<pk>/  — delete it, cascading to its grades

    On a homework assignment PATCH reaches the Homework behind it too, and
    DELETE is refused with 400: delete the Homework instead (spec 0007).

    The offering is fixed after creation: moving an assignment to another class
    would strand the grades already recorded against it.
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherRole()]

    @extend_schema(responses=SubjectAssignmentSerializer)
    def get(self, request, pk):
        assignment = get_object_or_404(assignment_queryset(request.user), pk=pk)
        return Response(
            SubjectAssignmentSerializer(assignment, context={'request': request}).data
        )

    @extend_schema(
        request=SubjectAssignmentWriteSerializer,
        responses=SubjectAssignmentSerializer,
    )
    def patch(self, request, pk):
        assignment = self._get_writable(request, pk)
        if isinstance(assignment, Response):
            return assignment

        serializer = SubjectAssignmentWriteSerializer(
            assignment, data=request.data, partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()

        return Response(
            SubjectAssignmentSerializer(assignment, context={'request': request}).data
        )

    @extend_schema(
        responses={204: None, 400: None},
        description='Category `homework` is refused with 400: delete the '
                    'homework through DELETE homeworks/<detail_id>/ instead.',
    )
    def delete(self, request, pk):
        assignment = self._get_writable(request, pk)
        if isinstance(assignment, Response):
            return assignment

        if assignment.is_homework and assignment.details is not None:
            return Response(
                {'detail': str(HOMEWORK_ASSIGNMENT_DELETE).format(
                    homework_id=assignment.detail_id,
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        assignment = get_object_or_404(
            SubjectAssignment.objects.select_related(*ASSIGNMENT_SELECT_RELATED), pk=pk,
        )
        if not can_manage_assignment(request.user, assignment):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )
        return assignment


# ── Grades ──

class SubjectAssignmentGradeListCreateAPIView(APIView):
    """
    GET  subject-assignments/<assignment_id>/grades/  — grades on one assignment
    POST subject-assignments/<assignment_id>/grades/  — grade one student

    The list is scoped per role: a student gets back their own row only, a
    parent their children's, a teacher the class they teach. Grading itself is
    a teacher's job — admin roles and psychologists read these rows, never
    write them.
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherRole()]
        return [IsAuthenticated()]

    @extend_schema(
        responses=SubjectGradeSerializer(many=True),
        parameters=[
            OpenApiParameter('student', int, description='Student profile id.'),
            OpenApiParameter('page', int),
            OpenApiParameter('page_size', int),
        ],
    )
    def get(self, request, assignment_id):
        assignment = get_object_or_404(
            assignment_queryset(request.user), pk=assignment_id,
        )

        rows = grade_queryset(request.user).filter(assignment=assignment)
        if request.query_params.get('student'):
            rows = rows.filter(student_id=request.query_params['student'])
        rows = rows.order_by(
            'student__user__last_name', 'student__user__first_name', 'id',
        )

        paginator = SubjectAssignmentPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = SubjectGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        request=SubjectGradeWriteSerializer,
        responses={201: SubjectGradeSerializer},
        description=(
            'Grades one student. The caller must teach the assignment\'s '
            'offering, and the student must be actively enrolled in that '
            'offering\'s class group. One grade per student per assignment — '
            'change an existing one with PATCH subject-grades/<pk>/. '
            '`grade` and `comments` are both optional and nullable, so a row '
            'can hold a comment without a mark, or stand as an empty '
            'placeholder until the work is marked.'
        ),
    )
    def post(self, request, assignment_id):
        assignment = get_object_or_404(
            SubjectAssignment.objects.select_related(*ASSIGNMENT_SELECT_RELATED),
            pk=assignment_id,
        )
        if not can_manage_assignment(request.user, assignment):
            return Response(
                {'detail': OWN_OFFERINGS_ONLY}, status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubjectGradeWriteSerializer(
            data=request.data,
            context={'request': request, 'assignment': assignment},
        )
        serializer.is_valid(raise_exception=True)
        grade = serializer.save(assignment=assignment)

        return Response(
            SubjectGradeSerializer(grade, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class SubjectGradeListAPIView(APIView):
    """
    GET subject-grades/ — every grade the caller may see, each row carrying its
    assignment inline.

    This is the one read endpoint that answers "what are this student's marks":
    a student calls it bare and gets their own, a parent gets their children's,
    a teacher gets the students of the offerings they teach, and admin roles
    and psychologists get the school. Narrow it with `student` when the caller
    can see more than one.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=SubjectGradeSerializer(many=True),
        parameters=ASSIGNMENT_FILTER_PARAMS + [
            OpenApiParameter('student', int, description='Student profile id.'),
            OpenApiParameter('assignment', int, description='Subject assignment id.'),
        ],
    )
    def get(self, request):
        rows = _apply_assignment_filters(
            grade_queryset(request.user), request.query_params, prefix='assignment__',
        )
        if request.query_params.get('student'):
            rows = rows.filter(student_id=request.query_params['student'])
        if request.query_params.get('assignment'):
            rows = rows.filter(assignment_id=request.query_params['assignment'])
        rows = rows.order_by('-assignment__date', '-created_at', '-id')

        paginator = SubjectAssignmentPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = SubjectGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


class OfferingSubjectGradeListAPIView(APIView):
    """
    GET offerings/<offering_id>/subject-grades/ — the offering's gradebook:
    every assignment, each with its grades nested inside (spec 0009).

    Visibility is exactly that of the per-assignment endpoints: assignments
    come from assignment_queryset widened with the homeroom one, grades from
    grade_queryset. A student therefore sees published assignments with only
    their own mark in each, and a teacher with no claim on the offering an
    empty list. Paginated over assignments, not grades.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=SubjectAssignmentWithGradesSerializer(many=True),
        parameters=[CATEGORY_PARAM] + DATE_PARAMS + PAGE_PARAMS,
        description=(
            'Assignments of one offering, newest first, each with a `grades` '
            'list ordered by student name. Scoped per role like GET '
            'subject-assignments/<id>/grades/.'
        ),
    )
    def get(self, request, offering_id):
        offering = get_object_or_404(SubjectOffering.objects.all(), pk=offering_id)
        user = request.user

        visible_grades = grade_queryset(user).order_by(
            'student__user__last_name', 'student__user__first_name', 'id',
        )
        rows = (
            assignment_queryset(user) | homeroom_assignment_queryset(user)
        ).filter(offering=offering).prefetch_related(
            Prefetch('grades', queryset=visible_grades, to_attr='visible_grades'),
        )
        rows = _apply_assignment_filters(rows, request.query_params).order_by(
            '-date', '-created_at', '-id',
        )

        paginator = SubjectAssignmentPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = SubjectAssignmentWithGradesSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


class HomeroomSubjectAssignmentListAPIView(APIView):
    """
    GET my-class/subject-assignments/ — every assignment set to the students in
    the caller's own homeroom class, across every subject taught to it.

    The mirror image of GET subject-assignments/, which is scoped to the
    offerings the caller teaches: this one is scoped to the class group they are
    homeroom teacher of, so their own assignments for their *other* classes stay
    out of it. Same payload, same filters, same ordering.

    Read-only, and read-only by construction rather than by a flag: writing to
    an assignment still needs a TeachingAssignment on its offering, so a
    homeroom teacher editing a colleague's assignment is the same 403 it has
    always been. A teacher with no homeroom class gets an empty list rather than
    an error.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        responses=SubjectAssignmentSerializer(many=True),
        parameters=ASSIGNMENT_FILTER_PARAMS,
        description=(
            'Subject assignments of the classes the caller is homeroom teacher '
            'of, every subject taught to them. Same payload as GET '
            'subject-assignments/. Empty when the caller has no homeroom '
            'assignment for the active academic year.'
        ),
    )
    def get(self, request):
        return _assignment_list_response(
            self, request, homeroom_assignment_queryset(request.user),
        )


class HomeroomSubjectGradeListAPIView(APIView):
    """
    GET teachers/my-class/subject-grades/ — every subject grade of the students
    in the caller's own homeroom class, across every subject taught to it.

    Read-only, and read-only by construction rather than by a flag: writing to
    a grade still needs a TeachingAssignment on the offering, so a homeroom
    teacher editing a colleague's grade is the same 403 it has always been. A
    teacher with no homeroom class gets an empty list rather than an error.
    """
    permission_classes = [IsAuthenticated, IsTeacherRole]

    @extend_schema(
        responses=SubjectGradeSerializer(many=True),
        parameters=ASSIGNMENT_FILTER_PARAMS + [
            OpenApiParameter('student', int, description='Student profile id.'),
        ],
        description=(
            'Subject grades of the classes the caller is homeroom teacher of. '
            'Same payload as GET subject-grades/. Empty when the caller has no '
            'homeroom assignment for the active academic year.'
        ),
    )
    def get(self, request):
        rows = _apply_assignment_filters(
            homeroom_grade_queryset(request.user),
            request.query_params,
            prefix='assignment__',
        )
        if request.query_params.get('student'):
            rows = rows.filter(student_id=request.query_params['student'])
        rows = rows.order_by(
            'student__user__last_name', 'student__user__first_name',
            '-assignment__date', '-created_at', '-id',
        )

        paginator = SubjectAssignmentPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        serializer = SubjectGradeSerializer(
            page, many=True, context={'request': request},
        )
        return paginator.get_paginated_response(serializer.data)


class SubjectGradeDetailAPIView(APIView):
    """
    GET    subject-grades/<pk>/  — single grade
    PATCH  subject-grades/<pk>/  — change the grade or its comments; `null` on
                                  either one clears it
    DELETE subject-grades/<pk>/  — remove the grade

    Writes are limited to the teachers of the offering the assignment belongs
    to; reads follow the same scoping as GET subject-grades/.
    """

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsTeacherRole()]

    @extend_schema(responses=SubjectGradeSerializer)
    def get(self, request, pk):
        grade = get_object_or_404(grade_queryset(request.user), pk=pk)
        return Response(
            SubjectGradeSerializer(grade, context={'request': request}).data
        )

    @extend_schema(request=SubjectGradeWriteSerializer, responses=SubjectGradeSerializer)
    def patch(self, request, pk):
        grade = self._get_writable(request, pk)
        if isinstance(grade, Response):
            return grade

        serializer = SubjectGradeWriteSerializer(
            grade,
            data=request.data,
            partial=True,
            context={'request': request, 'assignment': grade.assignment},
        )
        serializer.is_valid(raise_exception=True)
        grade = serializer.save()

        return Response(
            SubjectGradeSerializer(grade, context={'request': request}).data
        )

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        grade = self._get_writable(request, pk)
        if isinstance(grade, Response):
            return grade

        grade.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get_writable(request, pk):
        grade = get_object_or_404(
            SubjectGrade.objects.select_related(
                'student', 'student__user', 'assignment', 'assignment__offering',
            ),
            pk=pk,
        )
        if not can_manage_assignment(request.user, grade.assignment):
            return Response(
                {'detail': NO_PERMISSION}, status=status.HTTP_403_FORBIDDEN,
            )
        return grade


# ── Categories ──

class AssignmentCategoryListAPIView(APIView):
    """
    GET assignment-categories/ — every category an assignment may have.

    Categories are shared by all schools and managed in /admin/ (spec 0005), so
    this is the list a client should offer instead of a hard-coded one.

    `name` is in the language of the Accept-Language header — en, ru or kk —
    and English for anything else (spec 0006). `code` never changes with it.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=AssignmentCategorySerializer(many=True),
        parameters=[OpenApiParameter(
            'Accept-Language', str, OpenApiParameter.HEADER,
            enum=['en', 'ru', 'kk'],
            description='Language of `name`. Default: en.',
        )],
    )
    def get(self, request):
        rows = AssignmentCategory.objects.order_by('name', 'id')
        return Response(AssignmentCategorySerializer(rows, many=True).data)
