from django import template
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic.edit import CreateView
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.urls import reverse, reverse_lazy

from .forms import LessonForm, SubjectForm
from .models import Lesson, Subject, StudentGrade
from ..authentication.models import CustomUser
from django.shortcuts import render, redirect


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}

    html_template = loader.get_template('home/index.html')
    return HttpResponse(html_template.render(context, request))


@login_required(login_url="/login/")
def pages(request):
    context = {}
    # All resource paths end in .html.
    # Pick out the html file name from the url. And load that template.
    try:

        load_template = request.path.split('/')[-1]

        if load_template == 'admin':
            return HttpResponseRedirect(reverse('admin:index'))

        # elif load_template == 'pages':

        context['segment'] = load_template

        html_template = loader.get_template('home/' + load_template)
        return HttpResponse(html_template.render(context, request))

    except template.TemplateDoesNotExist:

        html_template = loader.get_template('home/page-404.html')
        return HttpResponse(html_template.render(context, request))

    except:
        html_template = loader.get_template('home/page-500.html')
        return HttpResponse(html_template.render(context, request))


@login_required(login_url="/login/")
def lessons_list(request):
    lessons = Lesson.objects.all()
    number_of_students = {}
    for lesson in lessons:
        number_of_students[lesson] = lesson.students.count()
    context = {'lessons': lessons, "number_of_students": number_of_students}
    html_template = loader.get_template('home/lessons.html')

    if request.method == 'POST':
        pass

    return HttpResponse(html_template.render(context, request))

@login_required(login_url="/login/")
def subjects_list(request):
    subjects = Subject.objects.all()
    context = {'subjects': subjects}
    html_template = loader.get_template('home/subjects.html')

    if request.method == 'POST':
        pass

    return HttpResponse(html_template.render(context, request))


@login_required(login_url="/login/")
def teachers_list(request):
    teachers = CustomUser.objects.filter(role='teacher')
    context = {'teachers': teachers}
    html_template = loader.get_template('home/teachers.html')

    if request.method == 'POST':
        pass

    return HttpResponse(html_template.render(context, request))

@login_required(login_url="/login/")
def grading(request):
    if request.method == 'POST':
        new_grade = StudentGrade()

        lesson_id = request.POST.get('lesson_id')
        if not Lesson.objects.filter(id=lesson_id).exists():
            return render(request, 'home/page-404.html')  # error lesson does not exist
        new_grade.lesson = Lesson.objects.get(id=lesson_id)

        student_id =  request.POST.get('student_id')
        if not CustomUser.objects.filter(id=student_id, role='student').exists():
            return render(request, 'home/page-404.html')  # error student does not exist
        new_grade.student = CustomUser.objects.get(id=student_id)

        new_grade.grade = request.POST.get('grade')
        new_grade.points = request.POST.get('points')
        new_grade.comment = request.POST.get('comment')
        new_grade.save()

        return redirect("home/grading.html")

    return render(request, 'home/grading.html')

@login_required(login_url="/login/")
def subject_details(request):
    subject_id = request.GET.get('subject_id')
    quarter = int(request.GET.get('quarter', '1'))
    subject = Subject.objects.get(id=subject_id)
    students = CustomUser.objects.filter(role='student', class_room=subject.classroom)
    lessons = Lesson.objects.filter(subject=subject)

    grades = {}
    for student in students:
        grades[student] = {}
        for lesson in lessons:
            if quarter == lesson.quarter:
                grades[student][lesson] = StudentGrade.objects.filter(lesson=lesson, student=student)

    context = {'grades': grades,
               'lessons': lessons,
               'subject_id': subject_id,
               'quarter': quarter
               }

    return render(request, 'home/subject_details.html', context)

@login_required(login_url="/login/")
def lesson_create(request):
    if request.method == "POST":
        form = LessonForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "👩‍🏫 Lesson created successfully!")
            return redirect("lessons")
    else:
        form = LessonForm()

    return render(request, "home/new_lesson.html", {"form": form})


@login_required(login_url="/login/")
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Subject created successfully!")
            return redirect("subjects")
    else:
        form = SubjectForm()

    return render(request, "home/new_subject.html", {"form": form})
