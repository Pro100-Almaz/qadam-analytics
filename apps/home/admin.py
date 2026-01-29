# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from django.utils.html import format_html
from django import forms
from .models import (
    Subject, AcademicYear, GradeLevel, ClassGroup, Enrollment,
    SubjectOffering, TeachingAssignment
)

from apps.lesson.models import Lesson


admin.site.register(GradeLevel)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "language_group", "status")
    list_filter = ("status", "language_group")
    search_fields = ("name",)


class TeachingAssignmentInline(admin.TabularInline):
    model = TeachingAssignment
    extra = 1


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = ("title", "date", "quarter", "order")


@admin.register(SubjectOffering)
class SubjectOfferingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "subject", "class_group", "academic_year", "get_primary_teacher")
    list_filter = ("academic_year", "subject", "class_group__grade_level")
    search_fields = ("subject__name", "class_group__letter")
    ordering = ("-academic_year__year", "class_group", "subject")
    inlines = [TeachingAssignmentInline, LessonInline]

    fieldsets = (
        (None, {
            "fields": ("subject", "class_group", "academic_year")
        }),
        ("Grading Configuration", {
            "fields": ("max_points", "grading_strategy"),
            "classes": ("collapse",)
        }),
    )

    def get_primary_teacher(self, obj):
        teacher = obj.get_primary_teacher()
        return str(teacher) if teacher else "-"
    get_primary_teacher.short_description = "Primary Teacher"


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "offering", "role")
    list_filter = ("role", "offering__academic_year")
    search_fields = ("teacher__user__first_name", "teacher__user__last_name")
    raw_id_fields = ("teacher", "offering")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "offering", "date", "quarter")
    list_filter = ("quarter", "offering__academic_year", "offering__subject")
    search_fields = ("title", "description")
    ordering = ("offering", "date", "order")
    date_hierarchy = "date"


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("year", "is_active", "archived")
    search_fields = ("year",)
    ordering = ("-year",)
    list_filter = ("is_active", "archived")


@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ("__str__", "grade_level", "letter", "academic_year")
    list_filter = ("academic_year", "grade_level")
    search_fields = ("letter",)
    ordering = ("academic_year", "grade_level", "letter")


class EnrollmentAdminForm(forms.ModelForm):
    """Custom form with validation for Enrollment."""

    class Meta:
        model = Enrollment
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get('student')
        academic_year = cleaned_data.get('academic_year')
        status = cleaned_data.get('status')
        class_group = cleaned_data.get('class_group')

        if student and academic_year and status == 'active':
            # Check for existing active enrollment in the same year
            existing = Enrollment.objects.filter(
                student=student,
                academic_year=academic_year,
                status='active'
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)

            if existing.exists():
                raise forms.ValidationError(
                    f"Студент {student} уже имеет активное зачисление в {academic_year}. "
                    "Сначала деактивируйте существующее зачисление."
                )

        # Validate class_group belongs to academic_year
        if class_group and academic_year:
            if class_group.academic_year != academic_year:
                raise forms.ValidationError(
                    f"Класс {class_group} не относится к учебному году {academic_year}."
                )

        return cleaned_data


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    form = EnrollmentAdminForm
    list_display = (
        "student_name", "student_avatar", "class_group", "academic_year",
        "status_badge", "start_date", "end_date", "days_enrolled"
    )
    list_display_links = ("student_name",)
    list_filter = ("status", "academic_year", "class_group__grade_level", "class_group")
    search_fields = (
        "student__user__first_name",
        "student__user__last_name",
        "student__user__username",
        "student__user__email",
    )
    ordering = ("-academic_year__year", "class_group", "student__user__last_name")
    raw_id_fields = ("student",)
    date_hierarchy = "start_date"
    list_per_page = 30
    actions = [
        'activate_selected', 'transfer_selected', 'graduate_selected',
        'withdraw_selected', 'bulk_create_enrollments'
    ]

    fieldsets = (
        ("Студент и класс", {
            "fields": ("student", "class_group", "academic_year")
        }),
        ("Статус зачисления", {
            "fields": ("status", "start_date", "end_date")
        }),
        ("Примечания", {
            "fields": ("notes",),
            "classes": ("collapse",)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'student', 'student__user', 'class_group', 'class_group__grade_level', 'academic_year'
        )

    def student_name(self, obj):
        return obj.student.user.get_full_name() or obj.student.user.username
    student_name.short_description = "Студент"
    student_name.admin_order_field = "student__user__last_name"

    def student_avatar(self, obj):
        if obj.student.user.avatar:
            return format_html(
                '<img src="{}" style="width: 30px; height: 30px; border-radius: 50%; object-fit: cover;" />',
                obj.student.user.avatar.url
            )
        return "—"
    student_avatar.short_description = ""

    def status_badge(self, obj):
        status_colors = {
            'active': ('#28a745', 'white'),
            'transferred': ('#ffc107', 'black'),
            'graduated': ('#17a2b8', 'white'),
            'withdrawn': ('#dc3545', 'white'),
            'on_leave': ('#6c757d', 'white'),
        }
        bg, fg = status_colors.get(obj.status, ('#6c757d', 'white'))
        return format_html(
            '<span style="background: {}; color: {}; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 500;">{}</span>',
            bg, fg, obj.get_status_display()
        )
    status_badge.short_description = "Статус"
    status_badge.admin_order_field = "status"

    def days_enrolled(self, obj):
        if obj.start_date:
            from django.utils import timezone
            end = obj.end_date or timezone.now().date()
            days = (end - obj.start_date).days
            return f"{days} дн."
        return "—"
    days_enrolled.short_description = "Дней"

    # Bulk Actions
    @admin.action(description="Активировать выбранные зачисления")
    def activate_selected(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"Активировано {updated} зачислений.")

    @admin.action(description="Перевести (transferred)")
    def transfer_selected(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='transferred', end_date=timezone.now().date())
        self.message_user(request, f"Переведено {updated} студентов.")

    @admin.action(description="Выпустить (graduated)")
    def graduate_selected(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='graduated', end_date=timezone.now().date())
        self.message_user(request, f"Выпущено {updated} студентов.")

    @admin.action(description="Отчислить (withdrawn)")
    def withdraw_selected(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='withdrawn', end_date=timezone.now().date())
        self.message_user(request, f"Отчислено {updated} студентов.")

    @admin.action(description="Массовое зачисление студентов")
    def bulk_create_enrollments(self, request, queryset):
        """Redirect to bulk enrollment page."""
        from django.contrib import messages
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        selected = queryset.values_list('student_id', flat=True)
        request.session['bulk_enroll_students'] = list(selected)
        return HttpResponseRedirect(reverse('admin_bulk_enroll_form'))

