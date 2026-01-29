from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django import forms
from django.contrib import messages
from apps.authentication.models import CustomUser, SchoolGroup, PsychologicalState, Supervisor, Teacher, Parent, Student
from apps.home.models import Enrollment, ClassGroup, AcademicYear


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("username", "email", "get_groups", "avatar_preview_small", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("avatar_preview",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Avatar", {"fields": ("avatar_preview", "avatar")}),
        ("Personal info", {
            "fields": ("first_name", "last_name", "email", "phone_number", "date_of_birth", "address", "school")
        }),
        ("Role Assignment", {"fields": ("groups",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "first_name", "last_name", "avatar", "groups"),
        }),
    )

    def get_groups(self, obj):
        """Display user's groups as a comma-separated list."""
        return ", ".join([g.name for g in obj.groups.all()]) or "No groups"
    get_groups.short_description = "Roles"

    def avatar_preview(self, obj):
        """Display large avatar preview in detail view."""
        if obj.avatar:
            return format_html(
                '<img src="{}" style="max-width: 200px; max-height: 200px; border-radius: 8px;" />',
                obj.avatar.url
            )
        return "No avatar"
    avatar_preview.short_description = "Current Avatar"

    def avatar_preview_small(self, obj):
        """Display small avatar thumbnail in list view."""
        if obj.avatar:
            return format_html(
                '<img src="{}" style="width: 32px; height: 32px; border-radius: 50%; object-fit: cover;" />',
                obj.avatar.url
            )
        return "-"
    avatar_preview_small.short_description = "Avatar"

class EnrollmentInline(admin.TabularInline):
    """Inline for managing student enrollments."""
    model = Enrollment
    extra = 0
    fields = ('class_group', 'academic_year', 'status', 'start_date', 'end_date')
    readonly_fields = ('start_date', 'end_date')
    ordering = ('-academic_year__year',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('class_group', 'academic_year')


class StudentAdminForm(forms.ModelForm):
    """Custom form for Student admin with class group selection."""
    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.none(),
        required=False,
        label="Класс (для зачисления)",
        help_text="Выберите класс для автоматического зачисления студента"
    )

    class Meta:
        model = Student
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get active academic year
        active_year = AcademicYear.objects.filter(is_active=True).first()
        if active_year:
            self.fields['class_group'].queryset = ClassGroup.objects.filter(
                academic_year=active_year
            ).select_related('grade_level').order_by('grade_level__number', 'letter')
            self.fields['class_group'].label = f"Класс ({active_year.year})"

        # Pre-fill class_group if editing existing student
        if self.instance and self.instance.pk:
            current_enrollment = self.instance.get_current_enrollment()
            if current_enrollment:
                self.fields['class_group'].initial = current_enrollment.class_group

    def save(self, commit=True):
        student = super().save(commit=commit)
        class_group = self.cleaned_data.get('class_group')

        if class_group and commit:
            # Get active academic year
            active_year = AcademicYear.objects.filter(is_active=True).first()
            if active_year:
                # Create or update enrollment
                Enrollment.enroll_student(
                    student=student,
                    class_group=class_group,
                    academic_year=active_year
                )
        return student


@admin.register(Student)
class StudentAdmin(ModelAdmin):
    form = StudentAdminForm
    model = Student
    list_display = (
        "avatar_thumbnail", "full_name", "email", "phone",
        "current_class_group", "enrollment_status", "academic_year"
    )
    list_display_links = ("full_name",)
    search_fields = ("user__first_name", "user__last_name", "user__username", "user__email")
    list_filter = ("academic_year", "school_group", "enrollments__status", "enrollments__class_group")
    ordering = ("user__last_name", "user__first_name")
    inlines = [EnrollmentInline]
    list_per_page = 25
    actions = ['bulk_enroll_students', 'activate_enrollments', 'deactivate_enrollments']

    fieldsets = (
        ("Основная информация", {
            "fields": ("user", "class_group")
        }),
        ("Дополнительно", {
            "fields": ("school_group", "academic_year", "subjects"),
            "classes": ("collapse",)
        }),
    )

    filter_horizontal = ("subjects",)
    raw_id_fields = ("user",)

    def avatar_thumbnail(self, obj):
        if obj.user.avatar:
            return format_html(
                '<img src="{}" style="width: 35px; height: 35px; border-radius: 50%; object-fit: cover;" />',
                obj.user.avatar.url
            )
        return format_html(
            '<span style="width: 35px; height: 35px; border-radius: 50%; background: #ddd; display: inline-block; text-align: center; line-height: 35px;">👤</span>'
        )
    avatar_thumbnail.short_description = ""

    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    full_name.short_description = "ФИО"
    full_name.admin_order_field = "user__last_name"

    def email(self, obj):
        return obj.user.email or "-"
    email.short_description = "Email"
    email.admin_order_field = "user__email"

    def phone(self, obj):
        return obj.user.phone_number or "-"
    phone.short_description = "Телефон"

    def current_class_group(self, obj):
        class_group = obj.get_current_class_group()
        if class_group:
            return format_html('<strong>{}</strong>', class_group)
        return format_html('<span style="color: #999;">—</span>')
    current_class_group.short_description = "Класс"

    def enrollment_status(self, obj):
        enrollment = obj.get_current_enrollment()
        if enrollment:
            status_colors = {
                'active': '#28a745',
                'transferred': '#ffc107',
                'graduated': '#17a2b8',
                'withdrawn': '#dc3545',
                'on_leave': '#6c757d',
            }
            color = status_colors.get(enrollment.status, '#6c757d')
            return format_html(
                '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{}</span>',
                color, enrollment.get_status_display()
            )
        return format_html('<span style="color: #999;">Не зачислен</span>')
    enrollment_status.short_description = "Статус"

    # Bulk Actions
    @admin.action(description="Зачислить выбранных студентов в класс")
    def bulk_enroll_students(self, request, queryset):
        """Bulk enroll selected students - redirects to intermediate page."""
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        selected = queryset.values_list('pk', flat=True)
        request.session['bulk_enroll_students'] = list(selected)
        return HttpResponseRedirect(reverse('admin_bulk_enroll_form'))

    @admin.action(description="Активировать зачисление")
    def activate_enrollments(self, request, queryset):
        """Activate enrollments for selected students."""
        active_year = AcademicYear.objects.filter(is_active=True).first()
        if not active_year:
            self.message_user(request, "Нет активного учебного года!", messages.ERROR)
            return

        count = 0
        for student in queryset:
            updated = Enrollment.objects.filter(
                student=student,
                academic_year=active_year
            ).update(status='active')
            count += updated

        self.message_user(request, f"Активировано {count} зачислений.", messages.SUCCESS)

    @admin.action(description="Деактивировать зачисление (отчислить)")
    def deactivate_enrollments(self, request, queryset):
        """Deactivate enrollments for selected students."""
        active_year = AcademicYear.objects.filter(is_active=True).first()
        if not active_year:
            self.message_user(request, "Нет активного учебного года!", messages.ERROR)
            return

        count = 0
        for student in queryset:
            updated = Enrollment.objects.filter(
                student=student,
                academic_year=active_year,
                status='active'
            ).update(status='withdrawn')
            count += updated

        self.message_user(request, f"Отчислено {count} студентов.", messages.SUCCESS)


# admin.site.register(Student)
admin.site.register(Parent)
admin.site.register(Teacher)
admin.site.register(Supervisor)

admin.site.register(SchoolGroup)
admin.site.register(PsychologicalState)
