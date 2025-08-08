from django.urls import path
from . import views

app_name = 'lesson'

urlpatterns = [
    path('', views.lessons_list, name='lessons'),
    path('grading/<int:pk>', views.grading, name='grading'),
    path('grading/submit', views.submit_all_topic_grades, name='submit_all_topic_grades'),
    path('grading/update/<int:pk>', views.update_grade, name='update_grade'),
    path('grading/display/<int:student_id>/<int:lesson_id>', views.display_grade, name='display_grade'),
    path('grading/delete/<int:student_id>/<int:lesson_id>', views.delete_grade, name='delete_grade'),
    path('create/', views.lesson_create, name='new_lesson'),
    path('create/<int:subject_id>/', views.lesson_create, name='new_lesson'),
    path('create/lesson_group_create', views.lesson_group_create, name='lesson_group_create'),
    path('topic/create/<int:pk>', views.create_topic, name='create_topic'),
    path('topic/update/<int:pk>', views.update_topic, name='update_topic'),
    path('topic/delete/<int:pk>', views.delete_topic, name='delete_topic'),
    path('topic/distribute/<int:pk>', views.distribute_topic_weights, name='distribute_topic_weights'),
    path('subtopic/create/<int:pk>', views.create_subtopic, name='create_subtopic'),
    path('subtopic/distribute/<int:lesson_id>', views.distribute_subtopic_weights, name='distribute_subtopic_weights'),


    path('<int:pk>/', views.lesson_details, name='lesson_details'),
    # path('list/<int:pk>/', views.lesson_details_json, name='lesson_details_json'),
    # path('comment-template/create/', views.comment_template_create, name='comment_template_create'),
    # path('comment-template/<int:comment_id>/update/', views.comment_template_update, name='comment_template_update'),
    # path('comment-template/<int:comment_id>/delete/', views.comment_template_delete, name='comment_template_delete'),

]