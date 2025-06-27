from django.contrib import admin
from apps.authentication.models import CustomUser, SchoolGroup, PsychologicalState, Supervisor, Teacher, Parent, Student

admin.site.register(Student)
admin.site.register(Parent)
admin.site.register(Teacher)
admin.site.register(Supervisor)

admin.site.register(CustomUser)
admin.site.register(SchoolGroup)
admin.site.register(PsychologicalState)
