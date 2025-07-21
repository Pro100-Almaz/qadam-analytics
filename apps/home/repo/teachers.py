from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.authentication.models import Teacher
from apps.home.models import Subject
from apps.lesson.models import Lesson


@login_required(login_url="/login/")
def teacher_details(request, pk):
    teacher = get_object_or_404(Teacher, user_id = pk)
    subjects = Subject.objects.filter(teacher = teacher)

    context = {
        'teacher': teacher,
        'subjects': subjects
    }
    return render(request, 'home/teacher_details.html', context)