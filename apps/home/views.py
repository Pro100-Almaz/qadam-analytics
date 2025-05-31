from django import template
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect

from apps.home.models import ClassRoom, Subject
from apps.authentication.models import CustomUser


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}
    return render(request, 'home/index.html', context)

@login_required(login_url="/login/")
def profile(request):
    if request.method == "POST":
        if 'avatar' in request.FILES:
            request.user.avatar = request.FILES['avatar']
            request.user.save()
            return redirect('profile')
    
    return render(request, 'home/profile.html')

@login_required(login_url="/login/")
def pages(request):
    context = {}
    try:
        load_template = request.path.split('/')[-1]
        if load_template == 'admin':
            return HttpResponseRedirect(reverse('admin:index'))
        context['segment'] = load_template
        return render(request, 'home/' + load_template, context)
    except template.TemplateDoesNotExist:
        return render(request, 'home/page-404.html', context)
    except:
        return render(request, 'home/page-500.html', context)

@login_required(login_url="/login/")
def teachers_list(request):
    teachers = CustomUser.objects.filter(role='teacher')
    context = {'teachers': teachers}
    return render(request, 'home/teachers.html', context)

@login_required(login_url="/login/")
def students_list(request):
    students = CustomUser.objects.filter(role='student')
    classrooms = ClassRoom.objects.all()
    context = {'students': students, 'classrooms': classrooms}
    return render(request, 'home/students.html', context)

@login_required(login_url="/login/")
def student_details(request, pk):
    student = get_object_or_404(CustomUser, pk=pk, role='student')
    subjects = Subject.objects.filter(classroom=student.classroom)
    context = {
        'student': student,
        'subjects': subjects,
        'total_subjects': subjects.count(),
    }
    return render(request, 'home/student_details.html', context)
