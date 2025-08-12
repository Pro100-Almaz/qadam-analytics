# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from .models import ClassRoom, Subject, AcademicYear

admin.site.register(ClassRoom)
admin.site.register(Subject)
@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("year",)
    search_fields = ("year",)
    ordering = ("-year",)

