from django.urls import path

from .views import (
    AchievementDetailAPIView,
    AchievementDownloadAPIView,
    AchievementListCreateAPIView,
    ClubEntryDetailAPIView,
    ClubEntryListCreateAPIView,
    ReadingEntryDetailAPIView,
    ReadingEntryListCreateAPIView,
)

app_name = 'achievement-api'

urlpatterns = [
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
]
