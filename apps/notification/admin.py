from django.contrib import admin

from apps.notification.models import Notification, RegisterNotify, LoginNotify, GradingNotify, PsychologicalNotify

admin.site.register(Notification)
admin.site.register(RegisterNotify)
admin.site.register(LoginNotify)
admin.site.register(GradingNotify)
admin.site.register(PsychologicalNotify)