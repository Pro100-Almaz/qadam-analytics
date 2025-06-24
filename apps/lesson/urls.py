from django.urls import path
from . import views

app_name = 'lesson'

urlpatterns = [
    path('', views.lessons_list, name='lessons'),
    path('grading/', views.grading, name='grading'),
    path('create/', views.lesson_create, name='new_lesson'),
    path('create/<int:subject_id>/', views.lesson_create, name='new_lesson'),
    path('create/lesson_group_create', views.lesson_group_create, name='lesson_group_create'),
    path('<int:pk>/', views.lesson_details, name='lesson_details'),
    path('list/<int:pk>/', views.lesson_details_json, name='lesson_details_json'),
    path('comment-template/create/', views.comment_template_create, name='comment_template_create'),
    path('comment-template/<int:comment_id>/update/', views.comment_template_update, name='comment_template_update'),
    path('comment-template/<int:comment_id>/delete/', views.comment_template_delete, name='comment_template_delete'),

] 