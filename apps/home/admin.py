# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from .models import *

admin.site.register(Lesson)
admin.site.register(Subject)
admin.site.register(ClassRoom)

