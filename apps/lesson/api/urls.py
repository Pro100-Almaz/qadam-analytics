from django.urls import path

from . import views

app_name = 'lesson-api'

urlpatterns = [
    # ── Lessons ──
    # GET  /api/v1/lessons/        list with filters: class_group, subject, quarter
    # POST /api/v1/lessons/        create lesson
    path('lessons/', views.LessonListCreateAPIView.as_view(), name='lesson-list-create'),

    # GET    /api/v1/lessons/<id>/  lesson detail with topics, students, student_grades
    # DELETE /api/v1/lessons/<id>/  delete lesson
    path('lessons/<int:pk>/', views.LessonDetailGetDeleteAPIView.as_view(), name='lesson-detail-delete'),

    # ── Topics ──
    # POST /api/v1/lessons/<lesson_id>/topics/  create parent topic
    path(
        'lessons/<int:lesson_id>/topics/',
        views.TopicCreateAPIView.as_view(),
        name='topic-create',
    ),

    # POST /api/v1/lessons/<lesson_id>/topics/distribute-weights/   get total weight of topic's subtopics
    path(
        'lessons/<int:lesson_id>/topics/distribute-weights/',
        views.TopicDistributeWeightsAPIView.as_view(),
        name='topic-distribute-weights',
    ),

    # PATCH  /api/v1/topics/<id>/  update topic
    # DELETE /api/v1/topics/<id>/  delete topic (rebalances weights)
    path('topics/<int:pk>/', views.TopicUpdateDeleteAPIView.as_view(), name='topic-update-delete'),

    # GET /api/v1/topics/<int:topic_id>/total-weight/
    path(
        'topics/<int:topic_id>/total-weight/',
        views.TopicTotalWeightAPIView.as_view(),
        name='topic-total-weight'
    ),

    # ── Subtopics ──
    # POST /api/v1/lessons/<lesson_id>/subtopics/  create subtopic
    path(
        'lessons/<int:lesson_id>/subtopics/',
        views.SubtopicCreateAPIView.as_view(),
        name='subtopic-create',
    ),

    # POST /api/v1/lessons/<lesson_id>/subtopics/distribute-weights/
    path(
        'lessons/<int:lesson_id>/subtopics/distribute-weights/',
        views.SubtopicDistributeWeightsAPIView.as_view(),
        name='subtopic-distribute-weights',
    ),

    # PATCH /api/v1/subtopics/<id>/  update subtopic
    # DELETE /api/v1/subtopics/<id>/ delete subtopic
    path('subtopics/<int:pk>/', views.SubtopicUpdateDeleteAPIView.as_view(), name='subtopic-update'),

    # ── Grading ──
    # GET   /api/v1/lessons/<lesson_id>/grading/  grading page data
    # POST  /api/v1/lessons/<lesson_id>/grading/  submit grades for a student
    # PATCH /api/v1/lessons/<lesson_id>/grading/  update grades for a student
    path(
        'lessons/<int:lesson_id>/grading/',
        views.GradingAPIView.as_view(),
        name='grading',
    ),

    # DELETE /api/v1/lessons/<lesson_id>/grading/<student_user_id>/
    path(
        'lessons/<int:lesson_id>/grading/<int:student_user_id>/',
        views.GradingDeleteAPIView.as_view(),
        name='grading-delete',
    ),

    # ── Calendar ──
    # GET /api/v1/calendar/lessons/  role-based calendar view
    path(
        'calendar/lessons/',
        views.CalendarLessonListAPIView.as_view(),
        name='calendar-lessons',
    ),

    # ── Quarter Snapshots ──
    path(
        'offerings/<int:pk>/freeze-quarter/',
        views.FreezeQuarterAPIView.as_view(),
        name='freeze-quarter',
    ),
    path(
        'students/<int:pk>/grade-history/',
        views.StudentGradeHistoryAPIView.as_view(),
        name='student-grade-history',
    ),

    # ── Audit ──
    path(
        'audit/grades/',
        views.GradeAuditLogAPIView.as_view(),
        name='grade-audit-log',
    ),
]
