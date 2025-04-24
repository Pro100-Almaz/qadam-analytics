from django import template
from django.contrib.auth.decorators import login_required
from django.views.generic.edit import CreateView
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.urls import reverse, reverse_lazy

from .forms import LessonForm
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

class LessonCreateView(CreateView):
    model = Lesson
    form_class = LessonForm
    template_name = 'home/new_lesson.html'
    success_url = reverse_lazy('lessons')


class SubjectCreateView(CreateView):
    pass
