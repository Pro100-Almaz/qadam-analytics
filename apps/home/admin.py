# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from .models import (
    Subject, AcademicYear, GradeLevel, ClassGroup, Enrollment,
    SubjectOffering, TeachingAssignment
)

from apps.lesson.models import Lesson, AssessmentItem, StudentScore


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


class AssessmentItemInline(admin.TabularInline):
    model = AssessmentItem
    extra = 0
    fields = ("name", "assessment_type", "max_points", "quarter", "date")


@admin.register(SubjectOffering)
class SubjectOfferingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "subject", "class_group", "academic_year", "get_primary_teacher")
    list_filter = ("academic_year", "subject", "class_group__grade_level")
    search_fields = ("subject__name", "class_group__letter")
    ordering = ("-academic_year__year", "class_group", "subject")
    inlines = [TeachingAssignmentInline, LessonInline, AssessmentItemInline]

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


@admin.register(AssessmentItem)
class AssessmentItemAdmin(admin.ModelAdmin):
    list_display = ("name", "offering", "assessment_type", "max_points", "quarter", "date")
    list_filter = ("assessment_type", "quarter", "offering__academic_year")
    search_fields = ("name",)
    ordering = ("offering", "quarter", "date")


@admin.register(StudentScore)
class StudentScoreAdmin(admin.ModelAdmin):
    list_display = ("student", "assessment_item", "points_earned", "graded_by", "graded_at")
    list_filter = ("assessment_item__offering__academic_year", "assessment_item__assessment_type")
    search_fields = (
        "student__user__first_name",
        "student__user__last_name",
        "assessment_item__name",
    )
    raw_id_fields = ("student", "assessment_item")
    ordering = ("-graded_at",)


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


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "class_group", "academic_year", "status", "start_date", "end_date")
    list_filter = ("status", "academic_year", "class_group")
    search_fields = (
        "student__user__first_name",
        "student__user__last_name",
        "student__user__username",
    )
    ordering = ("-academic_year__year", "class_group", "student")
    raw_id_fields = ("student",)
    date_hierarchy = "start_date"

    fieldsets = (
        (None, {
            "fields": ("student", "class_group", "academic_year")
        }),
        ("Status", {
            "fields": ("status", "start_date", "end_date")
        }),
        ("Notes", {
            "fields": ("notes",),
            "classes": ("collapse",)
        }),
    )

