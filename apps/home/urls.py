from django.urls import path, re_path
from apps.home import views

from apps.home.repo.students import students_list, student_details, classes, student_profile_update
from apps.home.repo.teachers import teacher_details, teacher_profile_update
from apps.home.repo.subject import subjects_list, my_subjects_list, subject_create, subject_details, archive_subject, \
    delete_subject, extract_subject, process_status_subject
from apps.home.views import delete_psychological_state

urlpatterns = [
    path('main/', views.main_page, name='main'),
    path('profile/', views.profile, name='profile'),
    path('profile/update/', views.profile_update, name='profile_update'),
    path('profile/edit_request/', views.profile_edit_request, name='profile_edit_request'),
    path('classes/', classes, name='classes'),
    path('students/', students_list, name='students'),
    path('students/<int:pk>', student_details, name='student_details'),
    path('students/<int:pk>/psychological_state_create', views.create_psychological_state, name='psychological_state_create'),
    path('students/<int:pk>/psychological_state_delete/<int:state_id>/', delete_psychological_state, name='psychological_state_delete'),
    path('students/<int:pk>/student_profile_update', student_profile_update, name='student_profile_update'),
    path('students/<int:pk>/psychological_state_create/template', views.create_psychological_state_template, name='psychological_state_create_template'),


    path('teachers', views.teachers_list, name='teachers'),
    path('teachers/<int:pk>', teacher_details, name='teacher_details'),
    path('teacher/<int:pk>/profile_update', teacher_profile_update, name='teacher_profile_update'),
    path('subjects', subjects_list, name='subjects'),
    path('subjects/archive', subjects_list, {'status': 'archived'}, name='subjects_archived'),
    path('subjects/planned', subjects_list, {'status': 'planned'}, name='subjects_planned'),
    path("subjects/<int:pk>/archive/", archive_subject, name="archive_subject"),
    path("subjects/<int:pk>/extract/", extract_subject, name="extract_subject"),
    path("subjects/<int:pk>/processing/", process_status_subject, name="processing_subject"),
    path("subjects/<int:pk>/delete/", delete_subject, name="delete_subject"),
    path('my_subjects', my_subjects_list, name='my_subjects'),
    path('my_subjects/<str:status>', my_subjects_list, name='my_subjects_status'),
    path('subjects/new', subject_create, name='new_subject'),
    path('subjects/<int:pk>', subject_details, name='subject_details'),

    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),
]
