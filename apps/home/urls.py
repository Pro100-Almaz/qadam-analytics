# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.urls import path, re_path
from apps.home import views, subject

urlpatterns = [

    # The home page
    path('', views.lessons_list, name='lessons'),
    path('lessons', views.lessons_list, name='lessons'),
    path('lessons/new', views.lesson_create, name='new_lesson'),
    path('lessons/<int:pk>', views.lesson_details, name='lesson_details'),
    path('grading', views.grading, name='grading'),
    path('students', views.students_list, name='students'),
    path('students/<int:pk>', views.student_details, name='student_details'),
    path('groups/new/', views.lesson_group_create, name='lesson_group_create'),
    path('teachers', views.teachers_list, name='teachers'),
    path('subjects', subject.subjects_list, name='subjects'),
    path('subjects/new', subject.subject_create, name='new_subject'),
    path('subjects/<int:pk>', subject.subject_details, name='subject_details'),
    path('comment-template/create/', views.comment_template_create, name='comment_template_create'),
    path('comment-template/<int:comment_id>/update/', views.comment_template_update, name='comment_template_update'),
    path('comment-template/<int:comment_id>/delete/', views.comment_template_delete, name='comment_template_delete'),
    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),

]
