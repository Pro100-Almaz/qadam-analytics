from django.contrib import admin
from .models import Lesson, StudentGrade, Comment, LessonGroup

admin.site.register(Lesson)
admin.site.register(StudentGrade)
admin.site.register(Comment)
admin.site.register(LessonGroup)
