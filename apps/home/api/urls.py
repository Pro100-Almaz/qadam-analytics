from django.urls import path

from . import views

app_name = 'home-api'

urlpatterns = [
    # Dashboard
    path('dashboard/stats/', views.DashboardStatsAPIView.as_view(), name='dashboard-stats'),
    path('dashboard/teacher-workload/', views.TeacherWorkloadAPIView.as_view(), name='teacher-workload'),

    # Academic years & class groups
    path('academic-years/', views.AcademicYearListAPIView.as_view(), name='academic-years'),
    path('class-groups/', views.ClassGroupListAPIView.as_view(), name='class-groups'),

    # Students — self-service (must be before <int:pk> routes)
    path('students/me/subjects/', views.StudentMySubjectsAPIView.as_view(), name='student-my-subjects'),
    path('students/me/teachers/', views.StudentMyTeachersAPIView.as_view(), name='student-my-teachers'),
    path('students/me/classmates/', views.StudentClassmatesAPIView.as_view(), name='student-classmates'),

    # Students
    path('students/', views.StudentListAPIView.as_view(), name='student-list'),
    path('students/<int:pk>/', views.StudentDetailAPIView.as_view(), name='student-detail'),
    path('students/<int:pk>/update/', views.StudentProfileUpdateAPIView.as_view(), name='student-update'),
    path(
        'students/<int:pk>/psychological-state/',
        views.PsychologicalStateCreateAPIView.as_view(),
        name='psychological-state-create',
    ),
    path(
        'psychological-states/<int:pk>/',
        views.PsychologicalStateDeleteAPIView.as_view(),
        name='psychological-state-delete',
    ),
    path(
        'psychological-state-templates/',
        views.PsychologicalStateTemplateListAPIView.as_view(),
        name='psychological-state-templates',
    ),

    # Teachers
    path('teachers/', views.TeacherListAPIView.as_view(), name='teacher-list'),
    path('teachers/<int:pk>/', views.TeacherDetailAPIView.as_view(), name='teacher-detail'),
    path('teachers/<int:pk>/update/', views.TeacherProfileUpdateAPIView.as_view(), name='teacher-update'),
    path('parent/teachers/', views.ParentTeacherListAPIView.as_view(), name='parent-teacher-list'),

    # Subjects
    path('subjects/', views.SubjectListAPIView.as_view(), name='subject-list'),
    path('subjects/new/', views.SubjectCreateAPIView.as_view(), name='subject-create'),
    path('subjects/<int:pk>/', views.SubjectDetailAPIView.as_view(), name='subject-detail'),
    path('subjects/<int:pk>/grades/', views.SubjectGradesAPIView.as_view(), name='subject-grades'),
    path('subjects/<int:pk>/status/', views.SubjectStatusAPIView.as_view(), name='subject-status'),
    path('subjects/<int:pk>/delete/', views.SubjectDeleteAPIView.as_view(), name='subject-delete'),
    path('my-subjects/', views.MySubjectsListAPIView.as_view(), name='my-subjects'),

    # Admin
    path('admin/rollover-year/', views.RolloverAcademicYearAPIView.as_view(), name='rollover-year'),

    # Enrollments
    path('enrollments/', views.EnrollmentListAPIView.as_view(), name='enrollment-list'),

    # Parent self-service
    path('parents/me/children/', views.ParentChildrenListAPIView.as_view(), name='parent-children'),
    path('parents/me/children/<int:student_pk>/', views.ParentChildDetailAPIView.as_view(), name='parent-child-detail'),
    path('parents/me/teachers/', views.ParentTeachersAPIView.as_view(), name='parent-my-teachers'),

    # Teacher dashboards (role-specific)
    path('teacher/dashboard/', views.TeacherRoleDashboardAPIView.as_view(), name='teacher-dashboard'),
    path('teacher/my-class/', views.HomeroomClassAPIView.as_view(), name='homeroom-class'),
    path('teacher/psychologist/', views.PsychologistDashboardAPIView.as_view(), name='psychologist-dashboard'),
    path(
        'teacher/psychologist/students/<int:pk>/',
        views.PsychologistStudentDetailAPIView.as_view(),
        name='psychologist-student-detail',
    ),
    path('teacher/my-classes/', views.TeacherMyClassesAPIView.as_view(), name='teacher-my-classes'),
    path(
        'teacher/my-classes/<int:class_group_id>/students/',
        views.TeacherClassStudentsAPIView.as_view(),
        name='teacher-class-students',
    ),
]
