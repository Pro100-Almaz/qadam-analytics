from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth.admin import UserAdmin
from apps.authentication.models import CustomUser, SchoolGroup, PsychologicalState, Supervisor, Teacher, Parent, Student

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("username", "email", "role", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info",
         {"fields": ("first_name", "last_name", "email", "phone_number", "address", "school", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("date_of_birth", "last_login")}),
    )

@admin.register(Student)
class StudentAdmin(ModelAdmin):
    model = Student
    list_display = ("full_name", "classroom_name")
    search_fields = ("user__first_name", "user__last_name", "classroom__name")

    def full_name(self, obj):
        return obj.user.get_full_name()
    full_name.short_description = "Full Name"

    def classroom_name(self, obj):
        return obj.classroom.name if obj.classroom else ""
    classroom_name.short_description = "Classroom"


# admin.site.register(Student)
admin.site.register(Parent)
admin.site.register(Teacher)
admin.site.register(Supervisor)

admin.site.register(SchoolGroup)
admin.site.register(PsychologicalState)
