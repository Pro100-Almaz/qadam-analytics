from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404

from apps.home.models import ClassRoom, Subject
from apps.authentication.models import CustomUser, PsychologicalStateTemplates, PsychologicalState
from apps.lesson.models import Lesson


@login_required(login_url='/login/')
def classes(request):
    return render(request, 'home/classes.html')


@login_required(login_url="/login/")
def students_list(request):
    selected_class = request.GET.get('class', 'all')
    students = CustomUser.objects.filter(role='student')

    if selected_class != 'all':
        students = students.filter(classroom__name = selected_class)

    classrooms = ClassRoom.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(students, 5)
    page_obj = paginator.get_page(page)

    context = {
        'students': students,
        'classrooms': classrooms,
        'page_obj': page_obj,
        'selected_class': selected_class,
    }
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
        'psychological_states': psychological_states
    }
    return render(request, 'home/student_details.html', context)