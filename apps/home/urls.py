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
    path('groups/new/', views.lesson_group_create, name='lesson_group_create'),
    path('teachers', views.teachers_list, name='teachers'),
    path('subjects', subject.subjects_list, name='subjects'),
    path('subjects/new', subject.subject_create, name='new_subject'),
    path('subjects/<int:pk>', subject.subject_details, name='subject_details'),
    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),

]
