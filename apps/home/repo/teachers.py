from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect

from core.decorators import role_required
from apps.authentication.forms import UserUpdateForm
from apps.authentication.models import Teacher
from apps.home.models import Subject, TeachingAssignment, SubjectOffering
from apps.lesson.models import Lesson


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def teacher_details(request, pk):
    teacher = get_object_or_404(Teacher, user_id=pk)

    # Get subjects via TeachingAssignment
    assignments = TeachingAssignment.objects.filter(
        teacher=teacher
    ).select_related('offering', 'offering__subject', 'offering__class_group')

    # Get unique subjects
    subject_ids = set(a.offering.subject_id for a in assignments)
    subjects = Subject.objects.filter(id__in=subject_ids)

    # Get offerings for context
    offerings = [a.offering for a in assignments]

    context = {
        'teacher': teacher,
        'subjects': subjects,
        'assignments': assignments,
        'offerings': offerings,
    }
    return render(request, 'home/teacher_details.html', context)


@role_required('admin', 'supervisor')
def teacher_profile_update(request, pk):
    if request.method == "POST":
        teacher = get_object_or_404(Teacher, id=pk)
        user = teacher.user

        # Update basic user information
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()

        teacher.gender = request.POST.get('gender')
        teacher.academic_degree = request.POST.get('academic_degree')
        teacher.occupation = request.POST.get('occupation')
        teacher.employment_type = request.POST.get('employment_type')

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
