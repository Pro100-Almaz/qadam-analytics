# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from apps.authentication.models import CustomUser, SchoolGroup, PsychologicalState

admin.site.register(CustomUser)
admin.site.register(SchoolGroup)
admin.site.register(PsychologicalState)
