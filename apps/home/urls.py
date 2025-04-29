# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.urls import path, re_path
from apps.home import views

urlpatterns = [

    # The home page
    path('', views.index, name='home'),
    path('lessons', views.lessons_list, name='lessons'),
    path('lessons/new', views.LessonCreateView.as_view(), name='new_lesson'),
    path('teachers', views.teachers_list, name='teachers'),
    path('subjects', views.subjects_list, name='subjects'),
    path('subjects/new', views.SubjectCreateView.as_view(), name='new_subject'),
    path('subject_details', views.subject_details, name='subject_details'),
    # Matches any html file
    re_path(r'^.*\.*', views.pages, name='pages'),

]
