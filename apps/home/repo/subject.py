from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from core.decorators import role_required
from core.permissions import can_modify_subject, can_access_subject, permission_denied_response
from apps.home.forms import SubjectForm
from apps.lesson.models import Lesson
from apps.home.models import Subject, SubjectOffering, TeachingAssignment, AcademicYear, Enrollment
from apps.authentication.models import CustomUser, Student, Teacher


def get_students_for_offering(offering):
    """Get count of students enrolled in an offering's class group."""
    return Enrollment.objects.filter(
        class_group=offering.class_group,
        academic_year=offering.academic_year,
        status='active'
    ).count()


def get_students_count_for_subject(subject, academic_year=None):
    """Get count of students who can access a subject (via offerings)."""
    offerings = SubjectOffering.objects.filter(subject=subject)
    if academic_year:
        offerings = offerings.filter(academic_year=academic_year)

    total = 0
    for offering in offerings:
        total += get_students_for_offering(offering)
    return total


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save(commit=False)
            subject.added_by = request.user
            subject.save()

            # Create SubjectOfferings for selected class groups
            academic_year = form.cleaned_data.get('academic_year')
            class_groups = form.cleaned_data.get('class_groups')

            if academic_year and class_groups:
                offerings_created = 0
                for class_group in class_groups:
                    # Create SubjectOffering if it doesn't exist
                    offering, created = SubjectOffering.objects.get_or_create(
                        subject=subject,
                        class_group=class_group,
                        academic_year=academic_year
                    )
                    if created:
                        offerings_created += 1

                        # If the creator is a teacher, assign them to the offering
                        if request.user.is_teacher():
                            try:
                                teacher = Teacher.objects.get(user=request.user)
                                TeachingAssignment.objects.get_or_create(
                                    offering=offering,
                                    teacher=teacher,
                                    defaults={'role': 'primary'}
                                )
                            except Teacher.DoesNotExist:
                                pass

                messages.success(
                    request,
                    f"Предмет '{subject.name}' создан и добавлен в {offerings_created} класс(ов)!"
                )
            else:
                messages.success(request, f"Предмет '{subject.name}' создан!")

            return redirect("subjects")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = SubjectForm()

    return render(request, "home/new_subject.html", {"form": form})


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal', 'parent')
def subjects_list(request, status=None):
    user = request.user
    if status is None:
        status = request.GET.get('status', 'active')

    year_id = request.GET.get('year')
    lang_filter = request.GET.get('lang', 'all')

    # Get current/selected academic year
    current_year = AcademicYear.objects.order_by('-year').first()
    if not year_id and current_year:
        year_id = str(current_year.id)

    # Role-based filtering
    # Admin, Principal, Supervisor - see all subjects
    # Teacher, Homeroom Teacher - see only their assigned subjects
    # Parent - see only subjects their children are enrolled in

    if user.is_admin() or user.is_principal() or user.is_manager():
        # Full access - get all subjects based on status
        if status == 'all':
            subjects = Subject.objects.all()
        elif status in ['archived', 'disabled']:
            subjects = Subject.objects.filter(status__in=['archived', 'disabled'])
        elif status == 'planned':
            subjects = Subject.objects.filter(status='planned')
        else:
            subjects = Subject.objects.filter(status='active')

    elif user.is_teacher() or user.is_homeroom_teacher():
        # Teachers see only subjects they're assigned to teach
        try:
            teacher = Teacher.objects.get(user=user)
            assignments = TeachingAssignment.objects.filter(teacher=teacher)
            if year_id:
                assignments = assignments.filter(offering__academic_year_id=year_id)
            subject_ids = set(a.offering.subject_id for a in assignments)
            subjects = Subject.objects.filter(id__in=subject_ids)
            if status != 'all':
                subjects = subjects.filter(status=status)
        except Teacher.DoesNotExist:
            subjects = Subject.objects.none()

    elif user.is_parent():
        # Parents see subjects their children are enrolled in
        from apps.authentication.models import Parent
        try:
            parent = Parent.objects.get(user=user)
            children = parent.students.all()

            # Get class groups where children are enrolled
            child_enrollments = Enrollment.objects.filter(
                student__in=children,
                status='active'
            )
            if year_id:
                child_enrollments = child_enrollments.filter(academic_year_id=year_id)

            class_group_ids = child_enrollments.values_list('class_group_id', flat=True)

            # Get subjects offered to those class groups
            offerings = SubjectOffering.objects.filter(class_group_id__in=class_group_ids)
            if year_id:
                offerings = offerings.filter(academic_year_id=year_id)

            subject_ids = offerings.values_list('subject_id', flat=True)
            subjects = Subject.objects.filter(id__in=subject_ids)
            if status != 'all':
                subjects = subjects.filter(status=status)
        except Parent.DoesNotExist:
            subjects = Subject.objects.none()
    else:
        subjects = Subject.objects.none()

    # Filter by language
    if lang_filter != 'all':
        subjects = subjects.filter(language_group=lang_filter)

    # Get offerings for these subjects in the selected year
    offerings_by_subject = {}
    if year_id:
        offerings = SubjectOffering.objects.filter(
            subject__in=subjects,
            academic_year_id=year_id
        ).select_related('class_group', 'subject')

        for offering in offerings:
            if offering.subject_id not in offerings_by_subject:
                offerings_by_subject[offering.subject_id] = []
            offerings_by_subject[offering.subject_id].append(offering)

    # Get class groups per subject
    subjects_class_groups = {}
    for subject_id, offs in offerings_by_subject.items():
        subjects_class_groups[subject_id] = [str(o.class_group) for o in offs]

    # Get student counts
    number_of_students = {}
    for subject in subjects:
        count = 0
        for offering in offerings_by_subject.get(subject.id, []):
            count += get_students_for_offering(offering)
        number_of_students[subject.id] = count

    langs = ['kaz', 'rus', 'eng']
    years = AcademicYear.objects.order_by('-year')

    page = request.GET.get('page')
    paginator = Paginator(subjects, 10)
    page_obj = paginator.get_page(page)

    context = {
        'subjects': subjects,
        'subjects_class_groups': subjects_class_groups,
        'number_of_students': number_of_students,
        'page_obj': page_obj,
        'status': status,
        'STATUS_CHOICES': Subject.STATUS_CHOICES,
        'years': years,
        'selected_year': int(year_id) if year_id else None,
        'lang_filter': lang_filter,
        'lang_groups': langs
    }
    return render(request, "home/subjects.html", context)


@role_required('teacher', 'homeroom_teacher')
def my_subjects_list(request, status=None):
    user = request.user

    if status is None:
        status = request.GET.get('status', 'active')

    # Get teacher's assignments
    try:
        teacher = Teacher.objects.get(user=user)
        assignments = TeachingAssignment.objects.filter(
            teacher=teacher
        ).select_related('offering', 'offering__subject')

        # Get unique subjects from assignments
        subject_ids = set(a.offering.subject_id for a in assignments)
        subjects = Subject.objects.filter(id__in=subject_ids)

        if status != 'all':
            subjects = subjects.filter(status=status)
    except Teacher.DoesNotExist:
        subjects = Subject.objects.none()

    # Get student counts
    number_of_students = {}
    for subject in subjects:
        number_of_students[subject.id] = get_students_count_for_subject(subject)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 10)
    page_obj = paginator.get_page(page)

    context = {
        'subjects': subjects,
        'number_of_students': number_of_students,
        'page_obj': page_obj,
        'status': status,
        'STATUS_CHOICES': Subject.STATUS_CHOICES,
        'is_my_subjects': True,
    }
    return render(request, "home/subjects.html", context)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def archive_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        if not can_modify_subject(request.user, subject):
            return permission_denied_response("You can only archive your own subjects.")

        subject.status = "archived"
        subject.save()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def extract_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        if not can_modify_subject(request.user, subject):
            return permission_denied_response("You can only activate your own subjects.")

        subject.status = "active"
        subject.save()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def process_status_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        if not can_modify_subject(request.user, subject):
            return permission_denied_response("You can only modify status of your own subjects.")

        subject.status = "planned"
        subject.save()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)


@role_required('admin', 'supervisor')
def delete_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.delete()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal', 'student')
def subject_details(request, pk):
    quarter = int(request.GET.get('quarter', '1'))
    subject = get_object_or_404(Subject.objects.select_related('added_by'), pk=pk)

    if not can_access_subject(request.user, subject):
        return permission_denied_response("You do not have permission to view this subject.")

    # Get current academic year
    current_year = AcademicYear.objects.filter(is_active=True).first()
    if not current_year:
        current_year = AcademicYear.objects.order_by('-year').first()

    # Get offerings for this subject
    offerings = SubjectOffering.objects.filter(
        subject=subject,
        academic_year=current_year
    ).select_related('class_group') if current_year else []

    # Get students enrolled in these offerings
    student_ids_seen = set()
    students = []
    for offering in offerings:
        enrollments = Enrollment.objects.filter(
            class_group=offering.class_group,
            academic_year=offering.academic_year,
            status='active'
        ).select_related('student', 'student__user')
        for e in enrollments:
            if e.student.id not in student_ids_seen:
                student_ids_seen.add(e.student.id)
                students.append(e.student)

    # Get lessons for this subject's offerings
    total_lessons = list(Lesson.objects.filter(offering__in=offerings))
    lessons = [l for l in total_lessons if l.quarter == quarter]
    lessons.sort(key=lambda x: x.created_at)

    # Calculate all grades in bulk (single query instead of L*S queries)
    all_grades_map = Lesson.calculate_grades_bulk(total_lessons, students)

    # Build lesson_avgs from bulk results
    lesson_avgs = {}
    for lesson in lessons:
        lesson_avgs[lesson.id] = {}
        for student in students:
            lesson_avgs[lesson.id][student.id] = round(
                all_grades_map.get((lesson.id, student.id), 0), 1
            )

    student_grades = {}
    total_student_grades = {}

    len_lessons = len(lessons)
    len_total_lessons = len(total_lessons)

    for student in students:
        total_student_grade = 0
        student_grade = 0

        # Sum grades for all lessons (using bulk results)
        for lesson in total_lessons:
            total_student_grade += all_grades_map.get((lesson.id, student.id), 0)

        # Sum grades for quarter lessons
        for lesson in lessons:
            student_grade += all_grades_map.get((lesson.id, student.id), 0)

        if len_lessons > 0:
            student_grade /= len_lessons
        if len_total_lessons > 0:
            total_student_grade /= len_total_lessons

        student_grades[student.id] = {
            'grade': round(student_grade, 1),
            'student_info': student.user.get_full_name()
        }
        total_student_grades[student.id] = {
            'grade': round(total_student_grade, 1)
        }

    top_grades = sorted(student_grades.items(), key=lambda x: x[1]['grade'], reverse=True)

    # Lessons pagination
    lessons_table = request.GET.get('lessons_page', '1')
    lessons_paginator = Paginator(lessons, 7)
    try:
        all_lessons = lessons_paginator.page(lessons_table)
    except PageNotAnInteger:
        all_lessons = lessons_paginator.page(1)
    except EmptyPage:
        all_lessons = lessons_paginator.page(lessons_paginator.num_pages)

    # Grades pagination
    grades_table = request.GET.get('grades_page', 1)
    grades_paginator = Paginator(top_grades, 5)
    try:
        all_grades = grades_paginator.page(grades_table)
    except PageNotAnInteger:
        all_grades = grades_paginator.page(1)
    except EmptyPage:
        all_grades = grades_paginator.page(grades_paginator.num_pages)

    # KPI metrics
    students_count = len(students)
    lessons_count = len(total_lessons)

    if student_grades:
        average_subject_points = round(
            sum(info['grade'] for info in student_grades.values()) / len(student_grades), 1
        )
    else:
        average_subject_points = 0

    students_with_grades = len([s for s in total_student_grades.values() if s['grade'] > 0])
    completion_percent = round((students_with_grades / students_count) * 100, 1) if students_count > 0 else 0

    # Get primary teacher for this subject (from first offering)
    primary_teacher = None
    if offerings:
        first_offering = offerings[0]
        primary_teacher = first_offering.get_primary_teacher()

    context = {
        'top_grades': top_grades,
        'all_grades': all_grades,
        'all_lessons': all_lessons,
        'lessons': lessons,
        'subject_id': pk,
        'quarter': quarter,
        'subject': subject,
        'students_count': students_count,
        'lessons_count': lessons_count,
        'average_subject_points': average_subject_points,
        'completion_percent': completion_percent,
        'subject_adder': subject.added_by,
        'teacher': primary_teacher,
        'offerings': offerings,
    }

    return render(request, 'home/subject_details.html', context)
