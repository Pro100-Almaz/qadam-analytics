# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils.html import format_html
from apps.home.forms import ClassGroupMultipleChoiceField, class_group_formfield
from apps.home.models import (
    Subject, AcademicYear, GradeLevel, ClassGroup, ClassGroupCollection,
    MinorClassGroup, Enrollment, SubjectOffering, TeachingAssignment,
    HomeroomTeacherAssignment
)

from apps.lesson.models import Lesson
from apps.authentication.models import Teacher


admin.site.register(GradeLevel)


class ClassGroupCategoryMixin:
    """For admins with a `class_group` FK: offer and label both categories."""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "class_group":
            return class_group_formfield(db_field, **kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def class_group_category(self, obj):
        return obj.class_group.get_category_display() if obj.class_group else "—"
    class_group_category.short_description = "Тип класса"
    class_group_category.admin_order_field = "class_group__category"


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "language_group", "status")
    list_filter = ("status", "language_group")
    search_fields = ("name",)


class TeachingAssignmentInline(admin.TabularInline):
    model = TeachingAssignment
    extra = 1
    autocomplete_fields = ("teacher",)


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = ("title", "date", "quarter", "order")


@admin.register(SubjectOffering)
class SubjectOfferingAdmin(ClassGroupCategoryMixin, admin.ModelAdmin):
    list_display = (
        "__str__", "subject", "class_group", "class_group_category",
        "academic_year", "get_primary_teacher",
    )
    list_filter = (
        "class_group__academic_year", "class_group__category", "subject",
        "class_group__grade_level",
    )
    search_fields = (
        "subject__name",
        "class_group__letter",
        "class_group__grade_level__number",
        "class_group__academic_year__year",
    )
    ordering = ("-class_group__academic_year__year", "class_group", "subject")
    inlines = [TeachingAssignmentInline, LessonInline]

    fieldsets = (
        (None, {
            "fields": ("subject", "class_group")
        }),
        ("Grading Configuration", {
            "fields": ("max_points", "grading_strategy"),
            "classes": ("collapse",)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "subject", "class_group", "class_group__grade_level",
            "class_group__academic_year",
        )

    def get_primary_teacher(self, obj):
        teacher = obj.get_primary_teacher()
        return str(teacher) if teacher else "-"
    get_primary_teacher.short_description = "Primary Teacher"


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "offering", "role")
    list_filter = ("role", "offering__class_group__academic_year")
    search_fields = ("teacher__user__first_name", "teacher__user__last_name")
    autocomplete_fields = ("teacher", "offering")
    ordering = ("-offering__class_group__academic_year__year", "offering", "teacher")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "teacher__user", "offering__subject", "offering__class_group",
            "offering__class_group__grade_level", "offering__class_group__academic_year",
        )


@admin.register(HomeroomTeacherAssignment)
class HomeroomTeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "class_group", "academic_year")
    list_filter = ("class_group__academic_year", "class_group__grade_level")
    search_fields = (
        "teacher__user__first_name",
        "teacher__user__last_name",
        "teacher__user__username",
        "class_group__letter",
    )
    ordering = ("-class_group__academic_year__year", "class_group", "teacher")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "teacher":
            kwargs["queryset"] = Teacher.objects.select_related("user").all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        homeroom_group, _ = Group.objects.get_or_create(name="HomeroomTeacher")
        obj.teacher.user.groups.add(homeroom_group)

    @staticmethod
    def _remove_role_if_unassigned(teacher_ids):
        homeroom_group = Group.objects.filter(name="HomeroomTeacher").first()
        if not homeroom_group:
            return

        teachers = Teacher.objects.filter(pk__in=teacher_ids).select_related("user")
        for teacher in teachers:
            if not teacher.homeroom_assignments.exists():
                teacher.user.groups.remove(homeroom_group)

    def delete_model(self, request, obj):
        teacher_id = obj.teacher_id
        super().delete_model(request, obj)
        self._remove_role_if_unassigned([teacher_id])

    def delete_queryset(self, request, queryset):
        teacher_ids = list(queryset.values_list("teacher_id", flat=True).distinct())
        super().delete_queryset(request, queryset)
        self._remove_role_if_unassigned(teacher_ids)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "offering", "date", "quarter")
    list_filter = ("quarter", "offering__class_group__academic_year", "offering__subject")
    search_fields = ("title", "description")
    ordering = ("offering", "date", "order")
    date_hierarchy = "date"


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("year", "is_active", "archived")
    search_fields = ("year",)
    ordering = ("-year",)
    list_filter = ("is_active", "archived")


class ClassGroupEnrollmentInline(admin.TabularInline):
    """Enroll students straight from the class / subgroup page."""
    model = Enrollment
    extra = 0
    fields = ("student", "status", "start_date", "end_date")
    raw_id_fields = ("student",)
    verbose_name = "Зачисление"
    verbose_name_plural = "Зачисления"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("student__user")


class BaseClassGroupAdmin(admin.ModelAdmin):
    """CRUD shared by classes and Подгруппы; subclasses pin one category."""
    category = None

    list_display = ("__str__", "grade_level", "letter", "academic_year", "students_count", "offerings_count")
    list_filter = ("academic_year", "grade_level")
    search_fields = ("letter", "grade_level__number", "academic_year__year")
    ordering = ("academic_year", "grade_level", "letter")
    exclude = ("category",)
    inlines = [ClassGroupEnrollmentInline]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            category=self.category
        ).select_related("grade_level", "academic_year").annotate(
            _students_count=Count(
                "enrollments", filter=Q(enrollments__status="active"), distinct=True
            ),
            _offerings_count=Count("subject_offerings", distinct=True),
        )

    def save_model(self, request, obj, form, change):
        obj.category = self.category
        super().save_model(request, obj, form, change)

    def students_count(self, obj):
        return obj._students_count
    students_count.short_description = "Учеников"
    students_count.admin_order_field = "_students_count"

    def offerings_count(self, obj):
        return obj._offerings_count
    offerings_count.short_description = "Предметов"
    offerings_count.admin_order_field = "_offerings_count"


class MajorClassGroupForm(forms.ModelForm):
    """The class form plus its constellation of подгруппы.

    `minor_groups` is deliberately left out of the admin's fieldsets: the
    change_form template renders it below the enrollment inline instead.
    """
    minor_groups = ClassGroupMultipleChoiceField(
        queryset=ClassGroup.objects.none(),
        required=False,
        label="Подгруппы",
        widget=FilteredSelectMultiple("подгруппы", is_stacked=False),
        help_text=(
            "Подгруппы, привязанные к этому классу. Одна подгруппа может быть "
            "привязана к нескольким классам."
        ),
    )

    class Meta:
        model = ClassGroup
        fields = ("grade_level", "letter", "academic_year")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        available = MinorClassGroup.objects.select_related("grade_level", "academic_year")
        if self.instance.academic_year_id:
            available = available.filter(academic_year_id=self.instance.academic_year_id)
        self.fields["minor_groups"].queryset = available.order_by("grade_level__number", "letter")
        self.fields["minor_groups"].initial = ClassGroupCollection.get_minor_groups(self.instance)

    def clean(self):
        cleaned_data = super().clean()
        academic_year = cleaned_data.get("academic_year")
        minor_groups = cleaned_data.get("minor_groups")
        if academic_year and minor_groups:
            other_year = [
                group.short_name for group in minor_groups
                if group.academic_year_id != academic_year.pk
            ]
            if other_year:
                self.add_error("minor_groups", ValidationError(
                    "Подгруппы из другого учебного года: %(groups)s.",
                    params={"groups": ", ".join(other_year)},
                ))
        return cleaned_data


@admin.register(ClassGroup)
class ClassGroupAdmin(BaseClassGroupAdmin):
    """Regular (major) classes — a student belongs to exactly one of them."""
    category = ClassGroup.MAJOR_CHOICE

    form = MajorClassGroupForm
    change_form_template = "admin/home/classgroup/change_form.html"
    fields = ("grade_level", "letter", "academic_year")
    list_display = (
        "__str__", "grade_level", "letter", "academic_year",
        "students_count", "offerings_count", "minor_groups_list",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("collection__minor_groups")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Binds the constellation, creating or deleting it as the selection needs.
        ClassGroupCollection.bind_minor_groups(
            form.instance, form.cleaned_data.get("minor_groups")
        )

    def minor_groups_list(self, obj):
        groups = ClassGroupCollection.get_minor_groups(obj)
        return ", ".join(group.short_name for group in groups) if groups else "—"
    minor_groups_list.short_description = "Подгруппы"


@admin.register(MinorClassGroup)
class MinorClassGroupAdmin(BaseClassGroupAdmin):
    """Подгруппы — minor groups a student joins alongside their class."""
    category = ClassGroup.MINOR_CHOICE

    list_display = (
        "__str__", "letter", "grade_level", "academic_year",
        "students_count", "offerings_count", "bound_classes",
    )
    ordering = ("academic_year", "letter")

    fields = ("letter", "grade_level", "academic_year")

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("collections__major")

    def bound_classes(self, obj):
        classes = [collection.major for collection in obj.collections.all()]
        return ", ".join(c.short_name for c in classes) if classes else "—"
    bound_classes.short_description = "Классы"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        letter = form.base_fields.get("letter")
        if letter:
            letter.label = "Название"
            letter.help_text = "Название подгруппы, например «English Advanced» или «Шахматы»."
        grade_level = form.base_fields.get("grade_level")
        if grade_level:
            grade_level.help_text = "Необязательно — оставьте пустым для подгруппы из разных параллелей."
        return form


@admin.register(Enrollment)
class EnrollmentAdmin(ClassGroupCategoryMixin, admin.ModelAdmin):
    list_display = (
        "student_name", "student_avatar", "class_group", "class_group_category",
        "academic_year", "status_badge", "start_date", "end_date", "days_enrolled"
    )
    list_display_links = ("student_name",)
    list_filter = (
        "status", "class_group__category", "class_group__academic_year",
        "class_group__grade_level", "class_group",
    )
    search_fields = (
        "student__user__first_name",
        "student__user__last_name",
        "student__user__username",
        "student__user__email",
    )
    ordering = ("-class_group__academic_year__year", "class_group", "student__user__last_name")
    raw_id_fields = ("student",)
    date_hierarchy = "start_date"
    list_per_page = 30
    actions = [
        'activate_selected', 'transfer_selected', 'graduate_selected',
        'withdraw_selected', 'bulk_create_enrollments'
    ]

    fieldsets = (
        ("Студент и класс", {
            "fields": ("student", "class_group")
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
            'student', 'student__user', 'class_group', 'class_group__grade_level',
            'class_group__academic_year',
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
        # Saved one by one so the "one major class group" rule is enforced.
        updated = 0
        skipped = []
        for enrollment in queryset.select_related('class_group', 'student__user'):
            enrollment.status = 'active'
            try:
                enrollment.save(update_fields=['status'])
            except ValidationError as e:
                skipped.append(f"{enrollment.student}: {'; '.join(e.messages)}")
                continue
            updated += 1

        self.message_user(request, f"Активировано {updated} зачислений.")
        if skipped:
            self.message_user(
                request, "Не активированы: " + " | ".join(skipped), messages.WARNING
            )

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
