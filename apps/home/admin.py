# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from .models import ClassRoom, Subject

admin.site.register(ClassRoom)
admin.site.register(Subject)

