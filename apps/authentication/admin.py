from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from apps.authentication.models import CustomUser, SchoolGroup, PsychologicalState, Supervisor, Teacher, Parent, Student


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("username", "email", "get_groups", "avatar_preview_small", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("avatar_preview",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Avatar", {"fields": ("avatar_preview", "avatar")}),
        ("Personal info", {
            "fields": ("first_name", "last_name", "email", "phone_number", "date_of_birth", "address", "school")
        }),
        ("Role Assignment", {"fields": ("groups",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "first_name", "last_name", "avatar", "groups"),
        }),
    )

    def get_groups(self, obj):
        """Display user's groups as a comma-separated list."""
        return ", ".join([g.name for g in obj.groups.all()]) or "No groups"
    get_groups.short_description = "Roles"

    def avatar_preview(self, obj):
        """Display large avatar preview in detail view."""
        if obj.avatar:
            return format_html(
                '<img src="{}" style="max-width: 200px; max-height: 200px; border-radius: 8px;" />',
                obj.avatar.url
            )
        return "No avatar"
    avatar_preview.short_description = "Current Avatar"

    def avatar_preview_small(self, obj):
        """Display small avatar thumbnail in list view."""
        if obj.avatar:
            return format_html(
                '<img src="{}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover;" />',
                obj.avatar.url
            )
        return "-"
    avatar_preview_small.short_description = "Avatar"

@admin.register(Student)
class StudentAdmin(ModelAdmin):
    model = Student
    list_display = ("full_name", "current_class_group", "academic_year")
    search_fields = ("user__first_name", "user__last_name", "user__username")
    list_filter = ("academic_year", "school_group")

    def full_name(self, obj):
        return obj.user.get_full_name()
    full_name.short_description = "Full Name"

    def current_class_group(self, obj):
        class_group = obj.get_current_class_group()
        return str(class_group) if class_group else "-"
    current_class_group.short_description = "Class Group"


# admin.site.register(Student)
admin.site.register(Parent)
admin.site.register(Teacher)
admin.site.register(Supervisor)

admin.site.register(SchoolGroup)
admin.site.register(PsychologicalState)
