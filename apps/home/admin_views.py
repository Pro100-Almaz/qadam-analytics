from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages

from apps.authentication.models import Student
from apps.home.models import ClassGroup, AcademicYear, Enrollment


@staff_member_required
def bulk_enroll_view(request):
    """Admin view for bulk enrolling students into a class."""

    if request.method == 'POST':
        student_ids = request.POST.getlist('students')
        class_group_id = request.POST.get('class_group')
        academic_year_id = request.POST.get('academic_year')

        if student_ids and class_group_id:
            try:
                class_group = ClassGroup.objects.get(pk=class_group_id)
                academic_year = (
                    AcademicYear.objects.get(pk=academic_year_id)
                    if academic_year_id
                    else AcademicYear.objects.filter(is_active=True).first()
                )

                if not academic_year:
                    messages.error(request, "Нет активного учебного года!")
                    return redirect('admin:authentication_student_changelist')

                count = 0
                for student_id in student_ids:
                    try:
                        student = Student.objects.get(pk=student_id)
                        Enrollment.enroll_student(student, class_group, academic_year)
                        count += 1
                    except Student.DoesNotExist:
                        continue

                messages.success(request, f"Успешно зачислено {count} студентов в {class_group}.")

            except ClassGroup.DoesNotExist:
                messages.error(request, "Выбранный класс не найден!")
            except Exception as e:
                messages.error(request, f"Ошибка: {str(e)}")

        else:
            messages.error(request, "Выберите студентов и класс!")

        # Clear session
        if 'bulk_enroll_students' in request.session:
            del request.session['bulk_enroll_students']

        return redirect('admin:authentication_student_changelist')

    # GET request - show form
    student_ids = request.session.get('bulk_enroll_students', [])

    if not student_ids:
        messages.warning(request, "Сначала выберите студентов для зачисления.")
        return redirect('admin:authentication_student_changelist')

    students = Student.objects.filter(pk__in=student_ids).select_related('user')
    active_year = AcademicYear.objects.filter(is_active=True).first()
    class_groups = (
        ClassGroup.objects.filter(academic_year=active_year)
        .select_related('grade_level')
        .order_by('grade_level__number', 'letter')
        if active_year
        else []
    )

    context = {
        'title': 'Массовое зачисление студентов',
        'students': students,
        'class_groups': class_groups,
        'academic_year': active_year,
        'opts': Student._meta,
        'has_permission': True,
    }
    return render(request, 'admin/bulk_enroll.html', context)
