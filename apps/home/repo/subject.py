from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import JsonResponse

from apps.home.forms import SubjectForm
from apps.lesson.models import Lesson
from apps.home.models import Subject
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


@login_required(login_url="/login/")
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            user = request.user
            form.instance.added_by = user
            if not form.instance.teacher:
                form.instance.teacher = user
            form.save()
            messages.success(request, "✅ Subject created successfully!")
            return redirect("subjects")
    else:
        form = SubjectForm()

    return render(request, "home/new_subject.html", {"form": form})


@login_required(login_url="/login/")
def subjects_list(request, status=None):
    # Default to active subjects only unless overridden by URLconf
    if status is None:
        status = request.GET.get('status', 'active')
    year_id = request.GET.get('year')

    if status == 'all':
        subjects = Subject.objects.all()
    elif status == 'archived':
        subjects = Subject.objects.filter(status__in=['archived', 'disabled'])
    elif status == 'planned':
        subjects = Subject.objects.filter(status__in=['planned'])
    else:
        subjects = Subject.objects.filter(status=status)

    from apps.home.models import AcademicYear
    current_year = AcademicYear.objects.order_by('-year').first()
    if not year_id and current_year:
        year_id = str(current_year.id)

    if year_id:
        subjects = subjects.filter(academic_year_id=year_id)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    years = AcademicYear.objects.order_by('-year')

    context = {
        'subjects': subjects,
        'number_of_students': get_students(subjects),
        'page_obj': page_obj,
        'status': status,
        'STATUS_CHOICES': Subject.STATUS_CHOICES,
        'years': years,
        'selected_year': int(year_id) if year_id else None,
        }
    return render(request, "home/subjects.html", context)


@login_required(login_url="/login/")
def my_subjects_list(request, status=None):
    user = CustomUser.objects.get(id=request.user.id)
    if status is None:
        status = request.GET.get('status', 'active')

    subjects = Subject.objects.filter(teacher__user=user)

    if status == 'all':
        subjects = Subject.objects.filter(teacher__user = user)
    elif status == 'archived':
        subjects = Subject.objects.filter(status__in=['archived', 'disabled'], teacher__user = user)
    elif status == 'planned':
        subjects = Subject.objects.filter(status__in=['planned'], teacher__user = user)
    else:
        subjects = Subject.objects.filter(status=status, teacher__user = user)

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

@login_required(login_url="/login/")
def archive_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.status = "archived"
        subject.save()
        return redirect("subjects")
    return (JsonResponse({"error": "Invalid request"}, status=400))

@login_required(login_url="/login/")
def extract_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.status = "active"
        subject.save()
        return redirect("subjects")
    return (JsonResponse({"error": "Invalid request"}, status=400))

@login_required(login_url="/login/")
def process_status_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.status = "planned"
        subject.save()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)

@login_required(login_url="/login/")
def delete_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.delete()
        return redirect("subjects")
    return JsonResponse({"error": "Invalid request"}, status=400)

@login_required(login_url="/login/")
def subject_details(request, pk):
    quarter = int(request.GET.get('quarter', '1'))
    subject = get_object_or_404(Subject.objects.select_related('teacher', 'added_by'), pk=pk)

    # Students enrolled in this subject
    students = Student.objects.filter(subjects=subject).select_related('user')
    lessons = Lesson.objects.filter(subject=subject, quarter=quarter).order_by('created_at')

    lesson_avgs = {}

    for lesson in lessons:
        lesson_avgs[lesson.id] = {}
        for student in students:
            lesson_avgs[lesson.id][student.id] = round(lesson.calculate_student_grade(student), 1)

    student_grades = {}

    len_lessons = len(lessons)
    for student in students:
        student_grade = 0
        for lesson in lessons:
            student_grade += lesson_avgs[lesson.id][student.id]
        student_grade /= len_lessons

        student_grades[student.id] = {}
        student_grades[student.id] = {
            'grade': student_grade,
            'student_info': student.user.get_full_name()
        }
    top_grades = sorted(student_grades.items(), key=lambda x: x[1]['grade'], reverse=True)


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
    students_with_grades = len([s for s in student_grades.values() if s['grade'] > 0])
    completion_percent = round((students_with_grades / students_count) * 100, 1) if students_count > 0 else 0

    context = {
        'top_grades': top_grades,
        'all_grades': all_grades,
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
