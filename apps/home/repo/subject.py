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
    return Subject.objects.filter(id=subject_id).count()


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
def subjects_list(request):
    status = request.GET.get('status', 'all')

    if status == 'all':
        subjects = Subject.objects.all()
    else:
        subjects = Subject.objects.filter(status=status)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    context = {
        'subjects': subjects,
        'number_of_students': get_students(subjects),
        'page_obj': page_obj,
        'status': request.GET.get('status', 'all'),
        'STATUS_CHOICES': Subject.STATUS_CHOICES
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


    students = Student.objects.filter(classroom=subject.teacher.classroom).select_related('user')

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

    context = {
        'grades': grades,
        'top_grades': top_grades,
        'num_lessons': max_num_of_grades,
        'lessons': lessons,
        'subject_id': pk,
        'quarter': quarter,
        'subject': subject,
        'students_count': get_students_count(pk),
        'subject_adder': subject.added_by,
        'teacher': subject.teacher,
    }

    return render(request, 'home/subject_details.html', context)
