from django import template
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from apps.home.models import ClassRoom, Subject
from apps.authentication.models import CustomUser, PsychologicalStateTemplates, PsychologicalState
from apps.lesson.models import Lesson


@login_required(login_url="/login/")
def index(request):
    context = {'segment': 'index'}
    return render(request, 'home/index.html', context)

@login_required(login_url="/login/")
def profile(request):
    user = request.user
    student = None
    if user.role == 'parent' and user.student_id:
        try:
            student = CustomUser.objects.get(id=user.student_id)
        except CustomUser.DoesNotExist:
            student = None

    context = {
        'user': user,
        'student': student
    }
    return render(request, 'home/profile.html', context)

@login_required(login_url="/login/")
def profile_update(request):
    if request.method == "POST":
        user = request.user
        
        # Update basic user information
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.phone_number = request.POST.get('phone_number')
        user.date_of_birth = request.POST.get('date_of_birth')
        user.occupation = request.POST.get('occupation')
        user.address = request.POST.get('address')
        
        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        
        try:
            user.save()
            messages.success(request, "Profile updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")
        
        return redirect('profile')
    
    return redirect('profile')

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
    page = request.GET.get('page')
    paginator = Paginator(teachers, 5)
    page_obj = paginator.get_page(page)

    context = {'teachers': teachers, "page_obj": page_obj}
    return render(request, 'home/teachers.html', context)

@login_required(login_url="/login/")
def students_list(request):
    students = CustomUser.objects.filter(role='student')
    classrooms = ClassRoom.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(students, 5)
    page_obj = paginator.get_page(page)

    context = {'students': students, 'classrooms': classrooms, 'page_obj': page_obj}
    return render(request, 'home/students.html', context)

@login_required(login_url="/login/")
def student_details(request, pk):
    student = get_object_or_404(CustomUser, pk=pk, role='student')
    subjects = Subject.objects.filter(classroom=student.classroom)
    lessons = Lesson.objects.filter(subject__in=subjects)
    templates = PsychologicalStateTemplates.objects.all()
    psychological_states = PsychologicalState.objects.filter(student_id=student.id)

    context = {
        'student': student,
        'subjects': subjects,
        'total_subjects': subjects.count(),
        'lessons': lessons,
        'templates': templates,
        'psychological_states': psychological_states,
    }
    return render(request, 'home/student_details.html', context)


@login_required(login_url="/login/")
def create_psychological_state(request, pk):
    if request.method == "POST":
        name = request.POST.get('state_name')
        comment = request.POST.get('comment')
        score = request.POST.get('star_rating')
        student_id = request.POST.get('student_id')

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(name=name, comment=comment, score = score, student_id=student_id)

    return redirect('student_details', pk=pk)


@login_required(login_url="/login/")
def create_psychological_state_template(request, pk):
    if request.method == "POST":
        name = request.POST.get('template_name')
        comment = request.POST.get('template_comment')

        if not PsychologicalStateTemplates.objects.filter(name=name).exists():
            PsychologicalStateTemplates.objects.create(name=name, comment=comment)

        PsychologicalState.objects.create(name=name, comment=comment)

    return redirect('student_details', pk=pk)
