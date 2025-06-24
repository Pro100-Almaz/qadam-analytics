from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator

from apps.home.forms import SubjectForm
from apps.lesson.models import Lesson, StudentGrade
from apps.home.models import Subject
from apps.authentication.models import CustomUser
from django.shortcuts import render, redirect, get_object_or_404


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


def get_students(subjects) -> dict:
    number_of_students = {}
    for subject in subjects:
        number_of_students[subject.id] = CustomUser.objects.filter(role='student', classroom=subject.classroom).count()
    return number_of_students

def get_students_count(subject_id: int) -> int:
    return Subject.objects.filter(id=subject_id).count()

@login_required(login_url="/login/")
def subjects_list(request):
    subjects = Subject.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    context = {
        'subjects': subjects,
        'number_of_students': get_students(subjects),
        'page_obj': page_obj,
        }
    return render(request, "home/subjects.html", context)


@login_required(login_url="/login/")
def my_subjects_list(request):
    user = CustomUser.objects.get(id=request.user.id)
    subjects = Subject.objects.filter(teacher=user)

    page = request.GET.get('page')
    paginator = Paginator(subjects, 5)
    page_obj = paginator.get_page(page)

    context = {'subjects': subjects, 'number_of_students': get_students(subjects), "page_obj": page_obj}
    return render(request, "home/subjects.html", context)


@login_required(login_url="/login/")
def subject_details(request, pk):
    quarter = int(request.GET.get('quarter', '1'))
    subject = get_object_or_404(Subject, pk=pk)
    students = CustomUser.objects.filter(role='student', classroom=subject.classroom)
    lessons = Lesson.objects.filter(subject=subject)
    subject_adder = subject.added_by
    teacher = subject.teacher


    grades = {}
    for student in students:
        grades[student] = {}
        for lesson in lessons:
            if quarter == lesson.quarter:
                grades[student][lesson] = StudentGrade.objects.filter(lesson=lesson, student=student)

    context = {'grades': grades,
               'lessons': lessons,
               'subject_id': pk,
               'quarter': quarter,
               'subject': subject,
               'students_count': get_students_count(pk),
               'subject_adder': subject_adder,
               'teacher': teacher
               }

    return render(request, 'home/subject_details.html', context)
