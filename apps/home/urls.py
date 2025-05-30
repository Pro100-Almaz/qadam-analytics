from django.urls import path, re_path
from apps.home import views, subject

urlpatterns = [
    path('profile/', views.profile, name='profile'),
    path('students', views.students_list, name='students'),
    path('students/<int:pk>', views.student_details, name='student_details'),
    path('teachers', views.teachers_list, name='teachers'),
    path('subjects', subject.subjects_list, name='subjects'),
    path('subjects/new', subject.subject_create, name='new_subject'),
    path('subjects/<int:pk>', subject.subject_details, name='subject_details'),
    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),
]
