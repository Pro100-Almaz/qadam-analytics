from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.html import format_html
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from apps.authentication.models import (
    ClubManager, CustomUser, School, SchoolGroup, PsychologicalState,
    Supervisor, Teacher, Parent, Student,
)
from apps.home.admin_forms import class_group_formfield
from apps.home.models import Enrollment, ClassGroup, AcademicYear, Subject
from apps.authentication.school_transfer import (
    realign_profile, stranded_by_move,
)
from core.admin_mixins import SchoolScopedAdminMixin


class SchoolRequiredMixin:
    """Mirrors the `user_has_school_unless_superuser` DB constraint in the form.

    Without this the admin writes school=NULL on a non-superuser and Postgres
    rejects it with an IntegrityError — a 500 where the user should simply be
    told the field is required.

    `is_superuser` is absent from the add form, which is correct: a user created
    there is never a superuser, so the school is unconditionally required.
    """

    def clean(self):
        cleaned = super().clean()
        if 'school' not in self.fields:
            return cleaned
        if not cleaned.get('is_superuser') and not cleaned.get('school'):
            self.add_error('school', 'Every user belongs to a school. Only superusers may have none.')
        return cleaned


class CustomUserCreationForm(SchoolRequiredMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser


class CustomUserChangeForm(SchoolRequiredMixin, UserChangeForm):
    """Also the gate on moving a user between schools.

    The move is allowed only for a user with nothing to leave behind. See
    `apps.authentication.school_transfer` for why: the person follows their
    `school`, but enrollments, lessons and marks are anchored to the old
    school's class groups and offerings and stay exactly where they are. The
    result is a student in one tenant whose record is in another, and a profile
    that fails its consistency check on every subsequent save.

    A form error rather than a silent no-op or a 500: the person doing it gets
    told what is in the way and can decide, which is the whole difference
    between a refused edit and a mysterious one.
    """

    class Meta(UserChangeForm.Meta):
        model = CustomUser

    def clean_school(self):
        school = self.cleaned_data.get('school')
        if not self.instance.pk or school is None:
            return school
        if school.pk == self.instance.school_id:
            return school

        blockers = stranded_by_move(self.instance)
        if blockers:
            listed = ', '.join(
                f'{count} {label}' for label, count in sorted(blockers.items()))
            raise ValidationError(
                f'{self.instance} cannot be moved to {school}: {listed} would '
                f'stay behind in {self.instance.school}. That data is anchored '
                f'to this school\'s class groups and offerings, not to the '
                f'person, so the move would split their record across two '
                f'schools and leave the profile uneditable. Moving a user with '
                f'a record is a transfer, not a field change — move or close '
                f'the rows above first.'
            )
        return school


@admin.register(CustomUser)
class CustomUserAdmin(SchoolScopedAdminMixin, UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ("username", "email", "get_groups", "avatar_preview_small", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("avatar_preview",)

    fieldsets = (
        ('Account Info', {"fields": ("username", "password")}),
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
            "fields": ("username", "email", "password1", "password2", "first_name", "last_name", "avatar", "school", "groups"),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """Remember which object is being edited, for the picker below."""
        form = super().get_form(request, obj, **kwargs)
        request._editing_user = obj
        return form

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Offer every school on the CHANGE form, one school on the ADD form.

        `SchoolScopedAdminMixin` pins the `school` picker to the active school
        so that a superuser viewing school A cannot create a row in school B
        while the header still says A. That is right for creation and wrong for
        correction: it also made a misfiled user impossible to put back, which
        is precisely what `legacy_school` is retained for.

        So the pin is lifted here, for existing users only, and whether the move
        is *allowed* is decided by `CustomUserChangeForm.clean_school` rather
        than by hiding the option. Passing `queryset` explicitly is what opts
        out of the mixin — it only pins when the caller named none.
        """
        if (
            db_field.name == 'school'
            and getattr(request, '_editing_user', None) is not None
            and request.user.is_superuser
        ):
            kwargs['queryset'] = School.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """Save, then say what else had to move with the user.

        `clean_school` has already refused anything with a record to strand, so
        the only things left to fix are the two nullable `Student` fields that
        still name the old school and would raise on the next save.
        """
        moved = change and 'school' in form.changed_data
        super().save_model(request, obj, form, change)
        if not moved:
            return
        for line in realign_profile(obj):
            messages.warning(request, f'{obj}: {line}')

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
    """Inline for managing student enrollments — classes and подгруппы alike."""
    model = Enrollment
    extra = 0
    fields = ('class_group', 'status', 'start_date', 'end_date')
    readonly_fields = ('start_date', 'end_date')
    ordering = ('-class_group__academic_year__year', 'class_group__category')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'class_group', 'class_group__grade_level', 'class_group__academic_year'
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'class_group':
            return class_group_formfield(db_field, **kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class StudentAdminForm(forms.ModelForm):
    """Custom form for Student admin with class group selection."""
    class_group = forms.ModelChoiceField(
        # None, not `.objects.none()`: a class body runs at import, where
        # there is no request and so no school scope. `__init__` below
        # sets the real queryset per form instance, inside the scope.
        queryset=None,
        required=False,
        label="Класс (для зачисления)",
        help_text="Выберите класс для автоматического зачисления студента"
    )

    # Declared, not left to `fields = '__all__'`: ModelFormMetaclass resolves an
    # auto-generated FK field's queryset at *class definition*, before any
    # request exists. Declaring them makes fields_for_model skip them;
    # __init__ supplies the real querysets per instance.
    school_group = forms.ModelChoiceField(queryset=None, required=False)
    academic_year = forms.ModelChoiceField(queryset=None, required=False)
    subjects = forms.ModelMultipleChoiceField(queryset=None, required=False)

    class Meta:
        model = Student
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['school_group'].queryset = SchoolGroup.objects.all()
        self.fields['academic_year'].queryset = AcademicYear.objects.order_by('-year')
        self.fields['subjects'].queryset = Subject.objects.all()

        # Always give class_group a queryset. The class body can no longer build
        # one, so leaving it unset when there is no active year would make the
        # widget raise instead of rendering an empty dropdown.
        majors = ClassGroup.objects.filter(
            category=ClassGroup.MAJOR_CHOICE,
        ).select_related('grade_level').order_by('grade_level__number', 'letter')
        active_year = AcademicYear.objects.filter(is_active=True).first()
        if active_year:
            majors = majors.filter(academic_year=active_year)
            self.fields['class_group'].label = f"Класс ({active_year.year})"
        self.fields['class_group'].queryset = majors

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
        "current_class_group", "current_minor_class_groups", "enrollment_status",
        "academic_year", "school_group"
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
            "fields": ("school_group", "academic_year", "medical_features", "subjects"),
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

    def current_minor_class_groups(self, obj):
        groups = obj.get_current_minor_class_groups()
        if groups:
            return ", ".join(group.short_name for group in groups)
        return format_html('<span style="color: #999;">—</span>')
    current_minor_class_groups.short_description = "Подгруппы"

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
        skipped = []
        for student in queryset:
            enrollments = Enrollment.objects.filter(
                student=student,
                class_group__academic_year=active_year
            ).select_related('class_group')
            # Saved one by one so the "one major class group" rule is enforced.
            for enrollment in enrollments:
                enrollment.status = 'active'
                try:
                    enrollment.save(update_fields=['status'])
                except ValidationError as e:
                    skipped.append(f"{student}: {'; '.join(e.messages)}")
                    continue
                count += 1

        self.message_user(request, f"Активировано {count} зачислений.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request, "Не активированы: " + " | ".join(skipped), messages.WARNING
            )

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
                class_group__academic_year=active_year,
                status='active'
            ).update(status='withdrawn')
            count += updated

        self.message_user(request, f"Отчислено {count} студентов.", messages.SUCCESS)


class ParentAdminForm(forms.ModelForm):
    students = forms.ModelMultipleChoiceField(
        # queryset=None, resolved in __init__: a class body runs at import,
        # where there is no request and so no school scope.
        queryset=None,
        widget=admin.widgets.FilteredSelectMultiple('Students', is_stacked=False),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['students'].queryset = Student.objects.all()
        self.fields['students'].label_from_instance = lambda obj: obj.get_admin_label()

    class Meta:
        model = Parent
        fields = '__all__'


@admin.register(Parent)
class ParentAdmin(ModelAdmin):
    form = ParentAdminForm
    list_display = ["full_name"]
    search_fields = ('user__first_name', 'user__last_name')

    def full_name(self, obj):
        return obj.user.get_full_name()

    fieldsets = (
        ('User Info', {'fields' : ('user',)}),
        ('Assigned Students', {"fields": ("students",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'students__user',
            'students__enrollments__class_group',
        )



@admin.register(Teacher)
class TeacherAdmin(ModelAdmin):
    list_display = ("full_name", "email", "employment_type", "occupation")
    list_display_links = ("full_name",)
    search_fields = (
        "user__first_name", "user__last_name", "user__username", "user__email",
    )
    ordering = ("user__last_name", "user__first_name")
    filter_horizontal = ("subjects",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    full_name.short_description = "ФИО"
    full_name.admin_order_field = "user__last_name"

    def email(self, obj):
        return obj.user.email or "-"
    email.short_description = "Email"
    email.admin_order_field = "user__email"


admin.site.register(Supervisor)
admin.site.register(ClubManager)

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    """The tenant list. The one admin page that is deliberately NOT scoped.

    Everything else on this site narrows to the school in the header; this
    cannot, because it *is* the thing the header chooses from. `School` carries
    no `school` column and no SCHOOL_PATH, so the mixin the site injects into
    every registration is a no-op here — nothing to stamp, nothing to filter.

    Superuser-only, and not because the data is sensitive: creating a tenant is
    the one action on this site that changes what every other page can mean.
    `selectable_schools` already limits the switcher to superusers, so a staff
    member who could add a School here would create one nobody can switch into.

    `slug` is read-only after creation. It is the stable internal key — every
    script's `--school` flag, every migration that names a tenant, and the
    `create_school` command all resolve through it — so renaming it in a form
    silently breaks callers that have no idea this page exists. `uuid` is
    already `editable=False`; it is shown because it is what crosses the
    network, and support questions start with it.
    """

    list_display = ('name', 'slug', 'short_name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug', 'short_name', 'contact_email')
    readonly_fields = ('uuid', 'created_at')
    fieldsets = (
        (None, {'fields': ('name', 'short_name', 'slug', 'is_active')}),
        ('Контакты', {'fields': ('address', 'contact_phone', 'contact_email')}),
        ('Служебное', {
            'fields': ('uuid', 'timezone', 'created_at'),
            'description': (
                'uuid is the public identifier — it is what the API and the '
                'JWT claim carry, never the numeric id.'
            ),
        }),
    )

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        """Only an empty tenant, and only one at a time.

        A populated school must not be deleted: every school FK is PROTECT, so
        the attempt could only ever produce a wall of protected-object errors,
        and `is_active=False` already means "no longer served" without taking a
        year of grades with it. Offering the button there is a promise the
        database will refuse to keep.

        A school with nothing pointing at it is the opposite case — a mistyped
        slug, a test row — and refusing *that* sends you to a shell to undo a
        typo you made in a form. So the button appears exactly when it would
        work.

        `obj is None` is the changelist, where returning False removes the bulk
        "delete selected" action. Deleting tenants en masse from a list of
        checkboxes is not a thing this site should make easy.
        """
        if not (request.user and request.user.is_superuser):
            return False
        if obj is None:
            return False
        return not self._has_dependents(obj)

    @staticmethod
    def _has_dependents(school):
        """Anything at all pointing at this school, in any tenant.

        `_base_manager`, not the reverse accessor: reverse managers go through
        the scoped default manager, so a school other than the active one would
        report itself empty and offer a delete that then fails at the database.
        """
        for relation in school._meta.related_objects:
            model = relation.related_model
            if model._meta.proxy:
                continue
            if model._base_manager.filter(
                    **{relation.field.name: school}).exists():
                return True
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return self.readonly_fields
        return self.readonly_fields + ('slug',)


@admin.register(SchoolGroup)
class SchoolGroupAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    """Orda houses. Per-school, so new ones are stamped on save."""


@admin.register(PsychologicalState)
class PsychologicalStateAdmin(SchoolScopedAdminMixin, admin.ModelAdmin):
    """Derives its school from the student; stamped when there is none."""
