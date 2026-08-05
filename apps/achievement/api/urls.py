from django.urls import path

from apps.achievement.api.views import (
    AchievementDetailAPIView,
    AchievementDownloadAPIView,
    AchievementListCreateAPIView,
    AttachmentDeleteAPIView,
    AttachmentUploadAPIView,
    ClubEntryDetailAPIView,
    ClubEntryListCreateAPIView,
    ReadingEntryDetailAPIView,
    ReadingEntryListCreateAPIView,
)
from apps.achievement.api.club_views import (
    ClubAttachmentDeleteAPIView,
    ClubAttachmentUploadAPIView,
    ClubAttendanceDetailAPIView,
    ClubAttendanceHistoryAPIView,
    ClubAvailableStudentListAPIView,
    ClubDetailAPIView,
    ClubListCreateAPIView,
    ClubMemberDeleteAPIView,
    ClubMemberListReplaceAPIView,
    StudentClubAttendanceListAPIView,
    StudentClubDetailAPIView,
    StudentClubListAPIView,
)

app_name = 'achievement-api'

urlpatterns = [
    # Managed clubs
    path('clubs/', ClubListCreateAPIView.as_view(), name='club-list-create'),
    path(
        'clubs/available-students/',
        ClubAvailableStudentListAPIView.as_view(),
        name='club-available-students',
    ),
    path('clubs/<int:pk>/', ClubDetailAPIView.as_view(), name='club-detail'),
    path(
        'students/<int:student_id>/clubs/',
        StudentClubListAPIView.as_view(),
        name='student-clubs',
    ),
    path(
        'students/<int:student_id>/clubs/<int:club_id>/',
        StudentClubDetailAPIView.as_view(),
        name='student-club-detail',
    ),
    path(
        'students/<int:student_id>/clubs/<int:club_id>/attendance/',
        StudentClubAttendanceListAPIView.as_view(),
        name='student-club-attendance',
    ),
    path(
        'clubs/<int:pk>/members/',
        ClubMemberListReplaceAPIView.as_view(),
        name='club-members',
    ),
    path(
        'clubs/<int:pk>/members/<int:student_id>/',
        ClubMemberDeleteAPIView.as_view(),
        name='club-member-delete',
    ),
    path(
        'clubs/<int:pk>/attendance/',
        ClubAttendanceHistoryAPIView.as_view(),
        name='club-attendance-history',
    ),
    path(
        'clubs/<int:pk>/attendance/<str:attendance_date>/sessions/<int:session_id>/',
        ClubAttendanceDetailAPIView.as_view(),
        name='club-attendance-detail',
    ),
    path(
        'clubs/<int:pk>/attachments/',
        ClubAttachmentUploadAPIView.as_view(),
        name='club-attachment-upload',
    ),
    path(
        'clubs/<int:pk>/attachments/<int:attachment_id>/',
        ClubAttachmentDeleteAPIView.as_view(),
        name='club-attachment-delete',
    ),

    # Achievements
    path(
        'students/<int:student_pk>/achievements/',
        AchievementListCreateAPIView.as_view(),
        name='achievement-list-create',
    ),
    path(
        'achievements/<int:pk>/',
        AchievementDetailAPIView.as_view(),
        name='achievement-detail',
    ),
    path(
        'achievements/<int:pk>/download/',
        AchievementDownloadAPIView.as_view(),
        name='achievement-download',
    ),

    # Reading entries
    path(
        'students/<int:student_pk>/reading-entries/',
        ReadingEntryListCreateAPIView.as_view(),
        name='reading-entry-list-create',
    ),
    path(
        'reading-entries/<int:pk>/',
        ReadingEntryDetailAPIView.as_view(),
        name='reading-entry-detail',
    ),

    # Club entries
    path(
        'students/<int:student_pk>/club-entries/',
        ClubEntryListCreateAPIView.as_view(),
        name='club-entry-list-create',
    ),
    path(
        'club-entries/<int:pk>/',
        ClubEntryDetailAPIView.as_view(),
        name='club-entry-detail',
    ),

    # Attachments (generic for all entry types)
    path(
        'attachments/<str:entry_type>/<int:entry_id>/',
        AttachmentUploadAPIView.as_view(),
        name='attachment-upload',
    ),
    path(
        'attachments/<int:pk>/',
        AttachmentDeleteAPIView.as_view(),
        name='attachment-delete',
    ),
]
