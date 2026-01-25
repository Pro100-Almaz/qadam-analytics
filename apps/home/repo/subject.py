from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import JsonResponse

from core.decorators import role_required
from core.permissions import can_modify_subject, can_access_subject, permission_denied_response
from apps.home.forms import SubjectForm
from apps.lesson.models import Lesson
from apps.home.models import SubjectOffering, TeachingAssignment
from apps.authentication.models import CustomUser, Student
from django.shortcuts import render, redirect, get_object_or_404


def get_students(subjects) -> dict:
    number_of_students = {}
    for subject in subjects:
        number_of_students[subject.id] = Student.objects.filter(subjects=subject).count()
    return number_of_students

def get_students_count(subject_id: int) -> int:
    # Return the number of students enrolled in this subject
    return Student.objects.filter(subjects__id=subject_id).count()


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            user = request.user
            form.instance.added_by = user
            if not form.instance.teacher:
                form.instance.teacher = user
            form.save()
            messages.success(request, "Subject created successfully!")
            return redirect("subjects")
    else:
        form = SubjectForm()

    return render(request, "home/new_subject.html", {"form": form})


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def subjects_list(request, status=None):
    # Default to active subjects only unless overridden by URLconf
    if status is None:
        status = request.GET.get('status', 'active')

    year_id = request.GET.get('year')
    lang_filter = request.GET.get('lang', 'all')

    subjects = Subject.objects.all()
    if status == 'all':
        pass
    elif status == 'archived' or status == 'disabled':
        subjects = Subject.objects.filter(status__in=['archived', 'disabled'])
    elif status == 'planned':
        subjects = Subject.objects.filter(status__in=['planned'])
    elif status == 'active':
        subjects = Subject.objects.filter(status__in=['active'])

    from apps.home.models import AcademicYear
    current_year = AcademicYear.objects.order_by('-year').first()
    if not year_id and current_year:
        year_id = str(current_year.id)

    if year_id:
        subjects = subjects.filter(academic_year_id=year_id)

    langs = ['kaz', 'rus', 'eng']
    if lang_filter != 'all':
        subjects = Subject.objects.filter(status=status, academic_year_id=year_id, language_group=lang_filter)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    years = AcademicYear.objects.order_by('-year')

    subjects_classrooms = {} #key = subject_id : value = {}

    students = Student.objects.all()
    for student in students:
        for subject in student.subjects.all():
            if subject.id not in subjects_classrooms:
                subjects_classrooms[subject.id] = []
            if student.classroom and student.classroom.name not in subjects_classrooms[subject.id]:
                subjects_classrooms[subject.id].append(student.classroom.name)


    context = {
        'subjects': subjects,
        'subjects_classrooms': subjects_classrooms,
        'number_of_students': get_students(subjects),
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
    user = CustomUser.objects.get(id=request.user.id)
    if status is None:
        status = request.GET.get('status', 'active')

    subjects = TeachingAssignment.get_subjects(user)

    # if status == 'all':
    #     subjects = Subject.objects.filter(teacher__user = user)
    # elif status == 'archived' or status== 'disabled':
    #     subjects = Subject.objects.filter(status__in=['archived', 'disabled'], teacher__user = user)
    # elif status == 'planned':
    #     subjects = Subject.objects.filter(status__in=['planned'], teacher__user = user)
    # else:
    #     subjects = Subject.objects.filter(status=status, teacher__user = user)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    context = {'subjects': subjects,
               'number_of_students': get_students(subjects),
               "page_obj": page_obj,
               'status': status,
               'STATUS_CHOICES': Subject.STATUS_CHOICES,
               'is_my_subjects': True,}
    return render(request, "home/subjects.html", context)

@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def archive_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        # Object-level permission: verify teacher owns this subject
        if not can_modify_subject(request.user, subject):
            return permission_denied_response("You can only archive your own subjects.")

        subject.status = "archived"
        subject.save()
        return redirect("subjects")
    return (JsonResponse({"error": "Invalid request"}, status=400))

@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def extract_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        # Object-level permission: verify teacher owns this subject
        if not can_modify_subject(request.user, subject):
            return permission_denied_response("You can only activate your own subjects.")

        subject.status = "active"
        subject.save()
        return redirect("subjects")
    return (JsonResponse({"error": "Invalid request"}, status=400))

@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher')
def process_status_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)

        # Object-level permission: verify teacher owns this subject
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
    subject = get_object_or_404(Subject.objects.select_related('teacher', 'added_by'), pk=pk)

    # Object-level permission: verify user can access this subject
    # - Admins/supervisors/principals can access all subjects
    # - Teachers can access their own subjects
    # - Students can only access subjects they're enrolled in
    if not can_access_subject(request.user, subject):
        return permission_denied_response("You do not have permission to view this subject.")

    # Students enrolled in this subject
    students = Student.objects.filter(subjects=subject).select_related('user')
    total_lessons = Lesson.objects.filter(subject=subject)
    lessons = total_lessons.filter(quarter=quarter).order_by('created_at')

    lesson_avgs = {}

    for lesson in lessons:
        lesson_avgs[lesson.id] = {}
        for student in students:
            lesson_avgs[lesson.id][student.id] = round(lesson.calculate_student_grade(student), 1)

    student_grades = {}
    total_student_grades = {}

    len_lessons = len(lessons)
    len_total_lessons = len(total_lessons)
    for student in students:
        total_student_grade = 0
        student_grade = 0
        for lesson in total_lessons:
            total_student_grade += lesson_avgs[lesson.id][student.id]
        for lesson in lessons:
            student_grade += lesson_avgs[lesson.id][student.id]

        if len_lessons == 0:
            student_grade = 0
        else:
            student_grade /= len_lessons

        if len_total_lessons == 0:
            total_student_grade = 0
        else:
            total_student_grade /= len_total_lessons

        student_grades[student.id] = {}
        student_grades[student.id] = {
            'grade': round(student_grade, 1),
            'student_info': student.user.get_full_name()
        }
        total_student_grades[student.id] = {}
        total_student_grades[student.id] = {
            'grade': round(total_student_grade, 1)
        }
    top_grades = sorted(student_grades.items(), key=lambda x: x[1]['grade'], reverse=True)

    #lessons paginator
    lessons_table = request.GET.get('lessons_page', '1')
    lessons_paginator = Paginator(lessons, 7)
    try:
        all_lessons = lessons_paginator.page(lessons_table)
    except PageNotAnInteger:
        all_lessons = lessons_paginator.page(1)
    except EmptyPage:
        all_lessons= lessons_paginator.page(lessons_paginator.num_pages)



    #grading table pagination
    grades_table = request.GET.get('grades_page', 1)
    grades_paginator = Paginator(top_grades, 5)
    try:
        all_grades = grades_paginator.page(grades_table)
    except PageNotAnInteger:
        all_grades = grades_paginator.page(1)
    except EmptyPage:
        all_grades = grades_paginator.page(grades_paginator.num_pages)


    # KPI metrics for the header cards
    students_count = students.count()
    lessons_count = Lesson.objects.filter(subject=subject).count()

    if student_grades:
        average_subject_points = round(sum(info['grade'] for info in student_grades.values()) / len(student_grades), 1)
    else:
        average_subject_points = 0

    # Completion: ratio of existing grades to expected grades (students × lessons)
    students_with_grades = len([s for s in total_student_grades.values() if s['grade'] > 0])
    completion_percent = round((students_with_grades / students_count) * 100, 1) if students_count > 0 else 0



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
        'teacher': subject.teacher,
    }

    return render(request, 'home/subject_details.html', context)
