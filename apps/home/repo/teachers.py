from django.shortcuts import get_object_or_404, render

from core.decorators import role_required
from apps.authentication.models import Teacher
from apps.home.models import Subject, TeachingAssignment


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal', 'parent')
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


