from django.urls import path

from apps.lesson.api import (
    analytics, analytics_attendance, analytics_subject, attendance_views,
    homework, views,
)

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

    path(
        'lessons/<int:lesson_id>/copy/',
        views.LessonCopyAPIView.as_view(),
        name='lesson-copy',
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

    # ── Teaching assignments ──
    # GET /api/v1/teaching-assignments/  filters: academic_year, class_group
    #                                    active subjects, primary teacher only
    path(
        'teaching-assignments/',
        attendance_views.TeachingAssignmentListAPIView.as_view(),
        name='teaching-assignment-list',
    ),

    # ── Subject schedules ──
    # GET  /api/v1/subject-schedules/   filters: offering, quarter, class_group,
    #                                   subject, academic_year, type
    #                                   (class_group matches free entries too)
    # POST /api/v1/subject-schedules/   create schedule for an offering + quarter,
    #                                   or a free entry with a description;
    #                                   class_group is required unless an
    #                                   offering supplies it
    path(
        'subject-schedules/',
        attendance_views.SubjectScheduleListCreateAPIView.as_view(),
        name='subject-schedule-list-create',
    ),

    # GET    /api/v1/subject-schedules/<pk>/  schedule with its sessions
    # PATCH  /api/v1/subject-schedules/<pk>/  update offering / class_group /
    #                                         description / quarter
    # DELETE /api/v1/subject-schedules/<pk>/  delete schedule
    path(
        'subject-schedules/<int:pk>/',
        attendance_views.SubjectScheduleDetailAPIView.as_view(),
        name='subject-schedule-detail',
    ),

    # ── Schedule sessions ──
    # GET  /api/v1/subject-schedules/<schedule_id>/sessions/  weekly slots, by time
    # POST /api/v1/subject-schedules/<schedule_id>/sessions/  add a slot
    #                                   (weekday + time_start + time_end)
    path(
        'subject-schedules/<int:schedule_id>/sessions/',
        attendance_views.ScheduleSessionListCreateAPIView.as_view(),
        name='schedule-session-list-create',
    ),

    # GET    /api/v1/schedule-sessions/<pk>/  single slot
    # PATCH  /api/v1/schedule-sessions/<pk>/  change weekday / time_start / time_end
    # DELETE /api/v1/schedule-sessions/<pk>/  delete slot
    path(
        'schedule-sessions/<int:pk>/',
        attendance_views.ScheduleSessionDetailAPIView.as_view(),
        name='schedule-session-detail',
    ),

    # ── Attendance ──
    # GET  /api/v1/schedule-sessions/<session_id>/attendance/  filters: date,
    #                                   date_from, date_to, student, status
    # POST /api/v1/schedule-sessions/<session_id>/attendance/  record attendance
    path(
        'schedule-sessions/<int:session_id>/attendance/',
        attendance_views.ScheduleAttendanceListCreateAPIView.as_view(),
        name='schedule-attendance-list-create',
    ),

    # GET    /api/v1/attendance/<pk>/  single attendance row
    # PATCH  /api/v1/attendance/<pk>/  change status / date / student
    # DELETE /api/v1/attendance/<pk>/  remove the row
    path(
        'attendance/<int:pk>/',
        attendance_views.ScheduleAttendanceDetailAPIView.as_view(),
        name='schedule-attendance-detail',
    ),

    # GET /api/v1/students/<student_id>/attendance/  one student's history
    path(
        'students/<int:student_id>/attendance/',
        attendance_views.StudentAttendanceListAPIView.as_view(),
        name='student-attendance-list',
    ),

    # ── Homework ──
    # POST /api/v1/homeworks/   create one homework per offering in `offerings`
    path(
        'homeworks/',
        homework.HomeworkCreateAPIView.as_view(),
        name='homework-create',
    ),

    # GET    /api/v1/homeworks/<pk>/  single homework
    # PUT    /api/v1/homeworks/<pk>/  replace description / max_grade / due_date /
    #                                 is_active, plus attachment add/remove
    # DELETE /api/v1/homeworks/<pk>/  delete homework
    path(
        'homeworks/<int:pk>/',
        homework.HomeworkDetailAPIView.as_view(),
        name='homework-detail',
    ),

    # ── Homework grades ──
    # GET  /api/v1/homeworks/<homework_id>/grades/  role-scoped grade list
    # POST /api/v1/homeworks/<homework_id>/grades/  grade one student
    path(
        'homeworks/<int:homework_id>/grades/',
        homework.HomeworkGradeListCreateAPIView.as_view(),
        name='homework-grade-list-create',
    ),

    # PATCH  /api/v1/homework-grades/<pk>/  change the grade / comments
    # DELETE /api/v1/homework-grades/<pk>/  remove the grade
    path(
        'homework-grades/<int:pk>/',
        homework.HomeworkGradeDetailAPIView.as_view(),
        name='homework-grade-detail',
    ),

    # GET /api/v1/teachers/my-class/homeworks/  published homework of the
    #                                   caller's homeroom class, every subject.
    #                                   Read-only; listed before the <int:...>
    #                                   route it shadows nothing of.
    path(
        'teachers/my-class/homeworks/',
        homework.HomeroomHomeworkListAPIView.as_view(),
        name='homeroom-homework-list',
    ),

    # GET /api/v1/teachers/<teacher_id>/homeworks/  homework set by one teacher.
    #                                   Teachers may only request their own id.
    path(
        'teachers/<int:teacher_id>/homeworks/',
        homework.TeacherHomeworkListAPIView.as_view(),
        name='teacher-homework-list',
    ),

    # GET /api/v1/students/<student_id>/homeworks/  homework assigned to one
    #                                   student, with their own grade inlined
    path(
        'students/<int:student_id>/homeworks/',
        homework.StudentHomeworkListAPIView.as_view(),
        name='student-homework-list',
    ),

    # ── Analytics ──
    # Read-only chart data. Missing topic grades count as zero throughout;
    # every payload carries a `coverage` figure so an unentered grade stays
    # distinguishable from a scored one.

    # GET /api/v1/analytics/students/<student_id>/offerings/<offering_id>/trajectory/
    #     per-lesson grade for one student with the class band around it.
    #     Filters: quarter, unit, date_from, date_to, include_class_stats
    path(
        'analytics/students/<int:student_id>/offerings/<int:offering_id>/trajectory/',
        analytics.StudentTrajectoryAPIView.as_view(),
        name='analytics-student-trajectory',
    ),

    # GET /api/v1/analytics/offerings/<offering_id>/topic-heatmap/
    #     student × topic matrix for one offering. Staff only.
    #     Filters: quarter, unit, date_from, date_to, group_by, include_subtopics
    path(
        'analytics/offerings/<int:offering_id>/topic-heatmap/',
        analytics.OfferingTopicHeatmapAPIView.as_view(),
        name='analytics-topic-heatmap',
    ),

    # GET /api/v1/analytics/students/<student_id>/subject-radar/
    #     one axis per subject for one quarter.
    #     Filters: academic_year, quarter, source, include_class_mean
    path(
        'analytics/students/<int:student_id>/subject-radar/',
        analytics.StudentSubjectRadarAPIView.as_view(),
        name='analytics-subject-radar',
    ),

    # ── Analytics: subject grades ──
    # The same three shapes over the assignment gradebook. Marks are a percent
    # of each assignment's own max_grade, and unmarked work is left out of the
    # averages unless missing=zero says otherwise.

    # GET /api/v1/analytics/students/<student_id>/offerings/<offering_id>/assignment-trajectory/
    #     per-assignment score for one student with the class band around it.
    #     Filters: category, date_from, date_to, missing, include_class_stats
    path(
        'analytics/students/<int:student_id>/offerings/<int:offering_id>/assignment-trajectory/',
        analytics_subject.StudentAssignmentTrajectoryAPIView.as_view(),
        name='analytics-assignment-trajectory',
    ),

    # GET /api/v1/analytics/offerings/<offering_id>/assignment-heatmap/
    #     student × assignment matrix for one offering. Staff only.
    #     Filters: category, date_from, date_to, missing
    path(
        'analytics/offerings/<int:offering_id>/assignment-heatmap/',
        analytics_subject.OfferingAssignmentHeatmapAPIView.as_view(),
        name='analytics-assignment-heatmap',
    ),

    # GET /api/v1/analytics/students/<student_id>/assignment-summary/
    #     one axis per subject, each split by lesson / exam / final.
    #     Filters: academic_year, quarter, category, date_from, date_to,
    #              missing, include_class_mean
    path(
        'analytics/students/<int:student_id>/assignment-summary/',
        analytics_subject.StudentAssignmentSummaryAPIView.as_view(),
        name='analytics-assignment-summary',
    ),

    # ── Analytics: attendance ──
    # An unrecorded slot is never counted as an absence; every rate carries the
    # `recorded` count it was taken over.

    # GET /api/v1/analytics/students/<student_id>/attendance-summary/
    #     one student's attendance by subject, weekday and month.
    #     Filters: academic_year, quarter, date_from, date_to, offering,
    #              include_class_stats
    path(
        'analytics/students/<int:student_id>/attendance-summary/',
        analytics_attendance.StudentAttendanceSummaryAPIView.as_view(),
        name='analytics-attendance-summary',
    ),

    # GET /api/v1/analytics/offerings/<offering_id>/attendance-heatmap/
    #     student × registered slot matrix for one offering. Staff only.
    #     Filters: quarter, date_from, date_to
    path(
        'analytics/offerings/<int:offering_id>/attendance-heatmap/',
        analytics_attendance.OfferingAttendanceHeatmapAPIView.as_view(),
        name='analytics-attendance-heatmap',
    ),

    # GET /api/v1/analytics/class-groups/<class_group_id>/attendance-overview/
    #     one class group ranked by attendance, with an at-risk list. Staff only.
    #     Filters: academic_year, quarter, date_from, date_to, at_risk_below
    path(
        'analytics/class-groups/<int:class_group_id>/attendance-overview/',
        analytics_attendance.ClassGroupAttendanceOverviewAPIView.as_view(),
        name='analytics-attendance-overview',
    ),
]
