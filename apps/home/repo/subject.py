from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse

from apps.home.forms import SubjectForm
from apps.lesson.models import Lesson, StudentGrade
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
def my_subjects_list(request):
    user = CustomUser.objects.get(id=request.user.id)
    subjects = Subject.objects.filter(teacher__user=user)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    context = {'subjects': subjects,
               'number_of_students': get_students(subjects),
               "page_obj": page_obj}
    return render(request, "home/subjects.html", context)

@login_required(login_url="/login/")
def archive_subject(request, pk):
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=pk)
        subject.status = "archived"
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

    lesson_ids = lessons.values_list('id', flat=True)
    student_users = [student.user for student in students]

    grades_qs = StudentGrade.objects.filter(
        student__in=student_users
    ).select_related('lesson', 'student')

    grades_lookup = {(grade.student_id, grade.lesson_id): grade for grade in grades_qs}

    grades = {}
    for student in students:
        student_grades = []
        for lesson in lessons:
            grade = grades_lookup.get((student.user_id, lesson.id))
            student_grades.append({'lesson': lesson, 'grade': grade})
        grades[student] = student_grades

    student_points = {student.user: 0 for student in students}
    max_num_of_grades = 1

    for student in students:
        user = student.user
        student_grades = [g for g in grades_qs if g.student == user]
        num = len(student_grades)
        if num > max_num_of_grades:
            max_num_of_grades = num
        total_points = sum(g.points for g in student_grades)
        student_points[user] = total_points


    for user in student_points:
        student_points[user] /= max_num_of_grades

    top_grades = sorted(student_points.items(), key=lambda x: x[1], reverse=True)

    # KPI metrics for the header cards
    students_count = students.count()
    lessons_count = lessons.count()

    # Average points across all student grades for the selected quarter's lessons
    subject_grades_qs = grades_qs.filter(lesson__in=lessons)
    if subject_grades_qs.exists():
        average_subject_points = int(sum(g.points for g in subject_grades_qs) / subject_grades_qs.count())
    else:
        average_subject_points = 0

    # Completion: ratio of existing grades to expected grades (students × lessons)
    total_expected_grades = students_count * lessons_count
    actual_grades_count = subject_grades_qs.count()
    completion_percent = int((actual_grades_count / total_expected_grades) * 100) if total_expected_grades > 0 else 0

    context = {
        'grades': grades,
        'top_grades': top_grades,
        'num_lessons': max_num_of_grades,
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
