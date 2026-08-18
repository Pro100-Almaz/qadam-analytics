from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.db.models import Count
from django.utils.text import Truncator

from apps.achievement.models import Attachment

from apps.lesson.models import Homework, HomeworkGrade, Topic, TopicGrade, MergedLessonComment


class SubtopicInline(admin.TabularInline):
    model = Topic
    fk_name = 'parent'
    extra = 0
    fields = ('title', 'order', 'weight', 'comment_template')
    verbose_name = "Subtopic"
    verbose_name_plural = "Subtopics"


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson', 'order', 'weight')
    list_filter = ('lesson',)
    search_fields = ('title', 'lesson__title')
    ordering = ('lesson', 'order')
    list_editable = ('order', 'weight')
    inlines = [SubtopicInline]

    fieldsets = (
        (None, {
            'fields': ('lesson', 'title')
        }),
        ('Settings', {
            'fields': ('order', 'weight', 'comment_template')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(parent__isnull=True)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if not instance.lesson_id:
                instance.lesson = form.instance.lesson
            instance.save()
        formset.save_m2m()


@admin.register(TopicGrade)
class TopicGradeAdmin(admin.ModelAdmin):
    list_display = ('topic', 'student', 'grade', 'comment_selected')
    list_filter = ('topic__lesson', 'comment_selected')
    search_fields = ('topic__title', 'student__user__first_name', 'student__user__last_name')


@admin.register(MergedLessonComment)
class MergedLessonCommentAdmin(admin.ModelAdmin):
    list_display = ('lesson', 'student', 'comment_text', 'is_merged')
    list_filter = ('lesson',)
    search_fields = ('comment_text', 'student__user__first_name')


class HomeworkAttachmentInline(GenericTabularInline):
    """Homework files live in the shared achievement.Attachment table."""
    model = Attachment
    extra = 0
    fields = ('file', 'original_name', 'file_type', 'uploaded_by', 'created_at')
    readonly_fields = ('created_at',)


class HomeworkGradeInline(admin.TabularInline):
    model = HomeworkGrade
    extra = 0
    fields = ('student', 'grade', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('student',)


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = (
        'short_description', 'offering', 'teacher', 'due_date',
        'max_grade', 'is_active', 'grade_count',
    )
    list_filter = (
        'is_active', 'due_date', 'offering__academic_year',
        'offering__subject', 'offering__class_group',
    )
    search_fields = (
        'description',
        'offering__subject__name',
        'teaching_assignment__teacher__user__first_name',
        'teaching_assignment__teacher__user__last_name',
    )
    date_hierarchy = 'due_date'
    ordering = ('-due_date', '-id')
    autocomplete_fields = ('offering', 'teaching_assignment')
    readonly_fields = ('created_at',)
    inlines = [HomeworkAttachmentInline, HomeworkGradeInline]

    fieldsets = (
        (None, {
            'fields': ('description', 'offering', 'teaching_assignment')
        }),
        ('Settings', {
            'fields': ('max_grade', 'due_date', 'is_active', 'created_at')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'offering', 'offering__subject', 'offering__class_group',
            'offering__academic_year',
            'teaching_assignment__teacher__user',
        ).annotate(_grade_count=Count('grades'))

    @admin.display(description='Description', ordering='description')
    def short_description(self, obj):
        return Truncator(obj.description).chars(60)

    @admin.display(description='Teacher')
    def teacher(self, obj):
        return obj.teaching_assignment.teacher

    @admin.display(description='Grades', ordering='_grade_count')
    def grade_count(self, obj):
        return obj._grade_count


@admin.register(HomeworkGrade)
class HomeworkGradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'homework', 'subject', 'grade', 'max_grade', 'created_at')
    list_filter = (
        'homework__offering__academic_year',
        'homework__offering__subject',
        'homework__offering__class_group',
    )
    search_fields = (
        'student__user__first_name', 'student__user__last_name',
        'student__user__username', 'homework__description',
    )
    ordering = ('-created_at',)
    autocomplete_fields = ('homework', 'student')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'student__user', 'homework', 'homework__offering',
            'homework__offering__subject', 'homework__offering__class_group',
        )

    @admin.display(description='Subject')
    def subject(self, obj):
        return obj.homework.offering.subject

    @admin.display(description='Max')
    def max_grade(self, obj):
        return obj.homework.max_grade
