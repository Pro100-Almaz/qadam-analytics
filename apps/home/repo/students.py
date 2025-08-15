from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect

from apps.home.models import ClassRoom, Subject
from apps.authentication.models import CustomUser, PsychologicalStateTemplates, PsychologicalState, Student
from apps.lesson.models import Lesson


@login_required(login_url='/login/')
def classes(request):
    return render(request, 'home/classes.html')


@login_required(login_url="/login/")
def students_list(request):
    selected_class = request.GET.get('class', 'all')
    selected_year = request.GET.get('year')
    students = Student.objects.all()

    if selected_class != 'all':
        students = students.filter(classroom__name=selected_class)

    if selected_year:
        students = students.filter(academic_year_id=selected_year)

    classrooms = ClassRoom.objects.all()
    from apps.home.models import AcademicYear
    years = AcademicYear.objects.order_by('-year')
    if not selected_year and years.exists():
        selected_year = str(years.first().id)
        students = students.filter(academic_year_id=selected_year)

    page = request.GET.get('page')
    paginator = Paginator(students, 5)
    page_obj = paginator.get_page(page)

    context = {
        'students': students,
        'classrooms': classrooms,
        'page_obj': page_obj,
        'selected_class': selected_class,
        'years': years,
        'selected_year': int(selected_year) if selected_year else None,
    }
    return render(request, 'home/students.html', context)


@login_required(login_url="/login/")
def student_details(request, pk):
    student = get_object_or_404(Student, user_id=pk)
    subjects = student.subjects.all()
    lessons = Lesson.objects.filter(subject__in=subjects)
    templates = PsychologicalStateTemplates.objects.all()
    psychological_states = PsychologicalState.objects.filter(student_id=student.id)
    last_state = psychological_states.last()
    last_updated = last_state.time_added if last_state else None
    non_student_subjects = Subject.objects.exclude(id__in=subjects.values_list('id', flat=True))


    context = {
        'student': student,
        'subjects': subjects,
        'total_subjects': subjects.count(),
        'lessons': lessons,
        'templates': templates,
        'psychological_states': psychological_states,
        'last_updated': last_updated,
        'non_student_subjects': non_student_subjects
    }
    return render(request, 'home/student_details.html', context)


@login_required(login_url="/login/")
def add_subject_to_student(request, pk):
    student = get_object_or_404(Student, user_id=pk)
    if request.method == 'POST':
        subject = request.POST.get('subject')
        student.subjects.add(subject)

    return redirect('student_details', pk=student.user.id)


@login_required(login_url="/login/")
def delete_subject_from_student(request, subject_id, student_id):
    student = get_object_or_404(Student, pk=student_id)
    if request.method == "POST":
        subject = get_object_or_404(Subject, pk=subject_id)
        student.subjects.remove(subject)

    return redirect('student_details', pk=student.user.id)
