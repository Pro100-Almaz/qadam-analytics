from django.contrib import admin

from apps.achievement.models import (
    Achievement, Club, ClubAttendance, ClubEntry, ClubSession, ReadingEntry,
)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ['student', 'category', 'academic_year', 'award_type', 'place', 'created_at']
    list_filter = ['category', 'academic_year']
    search_fields = ['student__user__first_name', 'student__user__last_name', 'award_type', 'place']
    raw_id_fields = ['student', 'academic_year', 'subject']
    date_hierarchy = 'created_at'


@admin.register(ReadingEntry)
class ReadingEntryAdmin(admin.ModelAdmin):
    list_display = ['student', 'title', 'month', 'academic_year', 'pages_read', 'test_score']
    list_filter = ['academic_year', 'month']
    search_fields = ['student__user__first_name', 'student__user__last_name', 'title']
    raw_id_fields = ['student', 'academic_year']


@admin.register(ClubEntry)
class ClubEntryAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'club_name', 'month', 'academic_year',
        'total_sessions', 'attended_sessions',
    ]
    list_filter = ['academic_year', 'month']
    search_fields = ['student__user__first_name', 'student__user__last_name', 'club_name']
    raw_id_fields = ['student', 'academic_year']


class ClubSessionInline(admin.TabularInline):
    model = ClubSession
    extra = 0


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ['name', 'manager', 'academic_year', 'start_date', 'end_date']
    list_filter = ['academic_year']
    search_fields = ['name', 'manager__user__first_name', 'manager__user__last_name']
    raw_id_fields = ['manager', 'academic_year']
    filter_horizontal = ['members']
    inlines = [ClubSessionInline]


@admin.register(ClubAttendance)
class ClubAttendanceAdmin(admin.ModelAdmin):
    list_display = ['session', 'student', 'date', 'status']
    list_filter = ['status', 'date']
    raw_id_fields = ['session', 'student']
