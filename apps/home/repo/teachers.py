from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect

from apps.authentication.models import Teacher
from apps.home.models import Subject, ClassRoom
from apps.lesson.models import Lesson


@login_required(login_url="/login/")
def teacher_details(request, pk):
    teacher = get_object_or_404(Teacher, user_id = pk)
    subjects = Subject.objects.filter(teacher = teacher)
    classrooms = ClassRoom.objects.filter(teacher = teacher)

    context = {
        'teacher': teacher,
        'subjects': subjects,
        'classrooms': classrooms,
    }
    return render(request, 'home/teacher_details.html', context)


@login_required(login_url="/login/")
def teacher_profile_update(request, pk):
    if request.method == "POST":
        teacher = get_object_or_404(Teacher, id = pk)
        user = teacher.user


        # Update basic user information
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.phone_number = request.POST.get('phone_number')
        user.address = request.POST.get('address')

        birth_date = request.POST.get('date_of_birth')
        if birth_date:
            user.date_of_birth = birth_date

        teacher.gender = request.POST.get('gender')
        teacher.academic_degree = request.POST.get('academic_degree')
        teacher.occupation = request.POST.get('occupation')

        classroom_id = request.POST.get('classroom')
        if classroom_id:
            teacher.classroom_id = classroom_id

        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']

        try:
            user.save()
            teacher.save()
            messages.success(request, f"Profile for {teacher.user.get_full_name()} updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")

        return redirect('teacher_details', pk=user.id)
    return redirect('teachers_list')

