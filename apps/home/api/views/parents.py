from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import Parent, Student, Teacher
from apps.home.models import TeachingAssignment, Enrollment, Subject, SubjectOffering
from apps.home.services import compute_child_grades
from apps.lesson.models import Lesson, QuarterGradeSnapshot

from apps.home.api.permissions import IsParent
from core.error_messages import CHILD_NOT_FOUND
from apps.home.api.serializers import (
    StudentDetailSerializer,
    ParentChildSerializer,
    ParentChildDetailSerializer,
    ParentTeacherDetailSerializer, ParentChildSubjectDetailSerializer,
)


class ParentChildrenListAPIView(APIView):
    permission_classes = [IsAuthenticated, IsParent]

    def get(self, request):
        parent = Parent.objects.get(user=request.user)
        children = parent.students.select_related('user', 'school_group').all()

        result = []
        for child in children:
            enrollment = child.get_current_enrollment()
            if enrollment:
                total_grade, quarter_grades, _ = compute_child_grades(child, enrollment)
                class_group_name = str(enrollment.class_group)
            else:
                total_grade = 0
                quarter_grades = {'1': None, '2': None, '3': None, '4': None}
                class_group_name = None

            avatar_url = child.user.avatar.url if child.user.avatar else None
            school_group_name = child.school_group.name if child.school_group else None

            result.append({
                'id': child.id,
                'user_id': child.user.id,
                'full_name': child.user.get_full_name(),
                'avatar': avatar_url,
                'class_group_name': class_group_name,
                'school_group': school_group_name,
                'student_total_grade': total_grade,
                'quarter_grades': quarter_grades,
            })

        serializer = ParentChildSerializer(result, many=True)
        return Response(serializer.data)


class ParentChildDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsParent]

    def get(self, request, student_pk):
        parent = Parent.objects.get(user=request.user)
        child = parent.students.select_related('user', 'school_group').filter(pk=student_pk).first()

        if not child:
            return Response(
                {'detail': CHILD_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = StudentDetailSerializer(child)
        return Response(serializer.data)


class ParentTeachersAPIView(APIView):
    permission_classes = [IsAuthenticated, IsParent]

    def get(self, request):
        parent = Parent.objects.get(user=request.user)
        children = parent.students.select_related('user').all()

        child_enrollments = Enrollment.objects.filter(
            student__in=children, status='active', academic_year__is_active=True,
        ).select_related('class_group', 'student')

        class_group_to_children = {}
        for e in child_enrollments:
            class_group_to_children.setdefault(e.class_group_id, []).append(
                e.student.user.get_full_name()
            )

        class_group_ids = list(class_group_to_children.keys())
        assignments = TeachingAssignment.objects.filter(
            offering__class_group_id__in=class_group_ids,
            offering__academic_year__is_active=True,
        ).select_related('teacher__user', 'offering__subject', 'offering__class_group')

        teacher_map = {}
        for a in assignments:
            tid = a.teacher.id
            if tid not in teacher_map:
                avatar_url = a.teacher.user.avatar.url if a.teacher.user.avatar else None
                teacher_map[tid] = {
                    'id': a.teacher.user.id,
                    'full_name': a.teacher.user.get_full_name(),
                    'avatar': avatar_url,
                    'email': a.teacher.user.email,
                    'subjects': [],
                    'children': set(),
                }

            subj_name = a.offering.subject.name
            if subj_name not in teacher_map[tid]['subjects']:
                teacher_map[tid]['subjects'].append(subj_name)

            for child_name in class_group_to_children.get(a.offering.class_group_id, []):
                teacher_map[tid]['children'].add(child_name)

        for t in teacher_map.values():
            t['children'] = sorted(t['children'])

        serializer = ParentTeacherDetailSerializer(list(teacher_map.values()), many=True)
        return Response(serializer.data)

class ParentChildSubjectDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, IsParent]

    def get(self, request, student_pk, subject_pk):
        child = Student.objects.filter(pk=student_pk).first()
        if not child:
            raise NotFound("Student not found")

        subject = Subject.objects.filter(pk=subject_pk).first()
        if not subject:
            raise NotFound("Subject not found")

        teacher = subject.assigned_teachers.first()

        class_group = child.get_current_class_group()
        if not class_group:
            return Response(
                {"detail": "Student does not belong to any class group"},
                status=status.HTTP_400_BAD_REQUEST
            )

        offering = SubjectOffering.objects.filter(
            subject=subject,
            class_group=class_group,
            academic_year=class_group.academic_year
        ).first()

        data = {
            'teacher': teacher,
            'subject': subject,
            'offering': offering,
            'class_group': class_group,
            'child': child,
            'lessons': Lesson.objects.filter(offering=offering) if offering else None,
        }

        serializer = ParentChildSubjectDetailSerializer(data)
        return Response(serializer.data)
