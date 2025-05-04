from django import template
from django.urls import path
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.urls import reverse, reverse_lazy

from apps.home.forms import SubjectForm
from apps.home.models import Lesson, Subject, StudentGrade
from apps.authentication.models import CustomUser
from django.shortcuts import render, redirect, get_object_or_404


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

@login_required(login_url="/login/")
def subjects_list(request):
    subjects = Subject.objects.all()
    context = {'subjects': subjects}
    html_template = loader.get_template('home/subjects.html')

    if request.method == 'POST':
        pass

    return HttpResponse(html_template.render(context, request))

@login_required(login_url="/login/")
def subject_details(request, pk):
    quarter = int(request.GET.get('quarter', '1'))
    subject = get_object_or_404(Subject, pk=pk)
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
               'subject_id': pk,
               'quarter': quarter,
               'subject': subject,
               }

    return render(request, 'home/subject_details.html', context)

