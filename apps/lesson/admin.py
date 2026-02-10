from django.contrib import admin
from .models import Topic, TopicGrade, MergedLessonComment


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
    list_display = ('lesson', 'student', 'comment_text')
    list_filter = ('lesson',)
    search_fields = ('comment_text', 'student__user__first_name')
