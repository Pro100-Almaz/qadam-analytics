import mimetypes
import os

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.achievement.models import Achievement, ClubEntry, ReadingEntry
from apps.authentication.models import Student
from core.permissions import can_access_student
from core.error_messages import (
    NO_ACCESS_STUDENT, NO_MODIFY_ACHIEVEMENT, NO_MODIFY_READING,
    NO_MODIFY_CLUB, NO_CERTIFICATE, CERTIFICATE_NOT_FOUND,
)

from .permissions import IsTeacherAdminOrSupervisor
from .serializers import (
    AchievementCreateSerializer,
    AchievementDetailSerializer,
    AchievementListSerializer,
    AchievementUpdateSerializer,
    ClubEntryCreateSerializer,
    ClubEntrySerializer,
    ReadingEntryCreateSerializer,
    ReadingEntrySerializer,
)


# ── Achievements ──

class AchievementListCreateAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    def get(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = Achievement.objects.filter(
            student=student
        ).select_related('student__user', 'academic_year', 'subject')

        year_id = request.query_params.get('year')
        if year_id:
            qs = qs.filter(academic_year_id=year_id)

        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        serializer = AchievementListSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data['student'] = student_pk

        serializer = AchievementCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        achievement = serializer.save()
        return Response(
            AchievementDetailSerializer(achievement).data,
            status=status.HTTP_201_CREATED,
        )


class AchievementDetailAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_achievement(self, pk):
        return get_object_or_404(
            Achievement.objects.select_related('student__user', 'academic_year', 'subject'),
            pk=pk,
        )

    def _check_access(self, request, achievement):
        if not can_access_student(request.user, achievement.student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _check_modify(self, request):
        perm = IsTeacherAdminOrSupervisor()
        if not perm.has_permission(request, self):
            return Response(
                {'detail': NO_MODIFY_ACHIEVEMENT},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request, pk):
        achievement = self._get_achievement(pk)
        denied = self._check_access(request, achievement)
        if denied:
            return denied
        return Response(AchievementDetailSerializer(achievement).data)

    def patch(self, request, pk):
        achievement = self._get_achievement(pk)
        denied = self._check_access(request, achievement) or self._check_modify(request)
        if denied:
            return denied

        serializer = AchievementUpdateSerializer(
            achievement, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(AchievementDetailSerializer(updated).data)

    def delete(self, request, pk):
        achievement = self._get_achievement(pk)
        denied = self._check_access(request, achievement) or self._check_modify(request)
        if denied:
            return denied
        achievement.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AchievementDownloadAPIView(APIView):
    def get(self, request, pk):
        achievement = get_object_or_404(Achievement, pk=pk)

        if not can_access_student(request.user, achievement.student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not achievement.certificate:
            return Response(
                {'detail': NO_CERTIFICATE},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_path = achievement.certificate.path
        if not os.path.exists(file_path):
            return Response(
                {'detail': CERTIFICATE_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )

        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or 'application/octet-stream'
        filename = os.path.basename(file_path)

        response = FileResponse(
            open(file_path, 'rb'),
            content_type=content_type,
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ── Reading Entries ──

class ReadingEntryListCreateAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    def get(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = ReadingEntry.objects.filter(
            student=student
        ).select_related('student__user', 'academic_year')

        year_id = request.query_params.get('year')
        if year_id:
            qs = qs.filter(academic_year_id=year_id)

        month = request.query_params.get('month')
        if month:
            qs = qs.filter(month=month)

        serializer = ReadingEntrySerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data['student'] = student_pk

        serializer = ReadingEntryCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(
            ReadingEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


class ReadingEntryDetailAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_entry(self, pk):
        return get_object_or_404(
            ReadingEntry.objects.select_related('student__user', 'academic_year'),
            pk=pk,
        )

    def _check_access(self, request, entry):
        if not can_access_student(request.user, entry.student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _check_modify(self, request):
        perm = IsTeacherAdminOrSupervisor()
        if not perm.has_permission(request, self):
            return Response(
                {'detail': NO_MODIFY_READING},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry)
        if denied:
            return denied
        return Response(ReadingEntrySerializer(entry).data)

    def patch(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry) or self._check_modify(request)
        if denied:
            return denied

        serializer = ReadingEntryCreateSerializer(entry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(ReadingEntrySerializer(updated).data)

    def delete(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry) or self._check_modify(request)
        if denied:
            return denied
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Club Entries ──

class ClubEntryListCreateAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsTeacherAdminOrSupervisor()]
        return [IsAuthenticated()]

    def get(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        qs = ClubEntry.objects.filter(
            student=student
        ).select_related('student__user', 'academic_year')

        year_id = request.query_params.get('year')
        if year_id:
            qs = qs.filter(academic_year_id=year_id)

        month = request.query_params.get('month')
        if month:
            qs = qs.filter(month=month)

        club_name = request.query_params.get('club_name')
        if club_name:
            qs = qs.filter(club_name__icontains=club_name)

        serializer = ClubEntrySerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, student_pk):
        student = get_object_or_404(Student, pk=student_pk)

        if not can_access_student(request.user, student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        data['student'] = student_pk

        serializer = ClubEntryCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(
            ClubEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


class ClubEntryDetailAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_entry(self, pk):
        return get_object_or_404(
            ClubEntry.objects.select_related('student__user', 'academic_year'),
            pk=pk,
        )

    def _check_access(self, request, entry):
        if not can_access_student(request.user, entry.student):
            return Response(
                {'detail': NO_ACCESS_STUDENT},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _check_modify(self, request):
        perm = IsTeacherAdminOrSupervisor()
        if not perm.has_permission(request, self):
            return Response(
                {'detail': NO_MODIFY_CLUB},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry)
        if denied:
            return denied
        return Response(ClubEntrySerializer(entry).data)

    def patch(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry) or self._check_modify(request)
        if denied:
            return denied

        serializer = ClubEntryCreateSerializer(entry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(ClubEntrySerializer(updated).data)

    def delete(self, request, pk):
        entry = self._get_entry(pk)
        denied = self._check_access(request, entry) or self._check_modify(request)
        if denied:
            return denied
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
