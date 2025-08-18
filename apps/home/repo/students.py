from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect

from apps.authentication.forms import UserUpdateForm
from apps.home.models import ClassRoom, Subject, AcademicYear
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

def calculate_quarter_grade(quarter, subject_id, student_id):
    student = get_object_or_404(Student, id=student_id)
    lessons = Lesson.objects.filter(subject_id=subject_id, quarter=quarter)
    lesson_quarter_grades = []
    for lesson in lessons:
        lesson_quarter_grades.append(round(lesson.calculate_student_grade(student), 1))
    try:
        subject_quarter_grade = sum(lesson_quarter_grades)/len(lesson_quarter_grades)
        return subject_quarter_grade
    except ZeroDivisionError:
        return 0

def grade_identifier(percent):
    grade = 0
    if percent > 80:
        grade = 5
    elif percent > 60:
        grade = 4
    elif percent > 40:
        grade = 3
    else:
        grade = 2
    return grade



@login_required(login_url="/login/")
def student_details(request, pk):
    student = get_object_or_404(Student, user_id=pk)
    subjects = student.subjects.all()
    lessons = Lesson.objects.filter(subject__in=subjects)
    templates = PsychologicalStateTemplates.objects.all()
    psychological_states = PsychologicalState.objects.filter(student_id=student.id)
    last_state = psychological_states.last()
    last_updated = last_state.time_added if last_state else None

    subject_quarter_grades = {}

    for quarter in [1,2,3,4]:
        subject_quarter_grades[quarter] = {}
        for subject in subjects:
            grade = calculate_quarter_grade(quarter, subject.id, student.id)
            subject_quarter_grades[quarter][subject.name] = grade if grade is not None else 0

    total_quarter_grades = {}
    num_subjects = len(subjects)
    student_total_grade = 0
    for quarter in [1,2,3,4]:
        to_add = 0
        for i in subject_quarter_grades[quarter]:
            to_add = subject_quarter_grades[quarter][i]
        to_add = round(to_add / num_subjects, 1)
        student_total_grade += round(to_add / 4, 1)
        total_quarter_grades[quarter] = grade_identifier(to_add)

    cumulative_subject_grades = {}
    for subject in subjects:
        to_add = 0
        for quarter in [1,2,3,4]:
            to_add += subject_quarter_grades[quarter][subject.name]
        to_add = round(to_add / 4, 1)
        cumulative_subject_grades[subject.name] = to_add

    academic_years = AcademicYear.objects.all()


    context = {
        'student_total_grade': student_total_grade,
        'total_quarter_grades': total_quarter_grades,
        'cumulative_subject_grades': cumulative_subject_grades,
        'subject_quarter_grades': list(subject_quarter_grades.items()),
        'academic_years': academic_years,
        'student': student,
        'subjects': subjects,
        'total_subjects': subjects.count(),
        'lessons': lessons,
        'templates': templates,
        'psychological_states': psychological_states,
        'last_updated': last_updated,
    }
    return render(request, 'home/student_details.html', context)


@login_required(login_url="/login/")
def student_profile_update(request, pk):
    if request.method == "POST":
        student = get_object_or_404(Student, id = pk)
        user = student.user


        # Update basic user information
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()

        birth_date = request.POST.get('date_of_birth')
        if birth_date:
            user.date_of_birth = birth_date

        student.school_group = request.POST.get('school_group')
        student.academic_year = request.POST.get('academic_year')

        classroom_id = request.POST.get('classroom')
        if classroom_id:
            student.classroom_id = classroom_id

        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']

        try:
            user.save()
            student.save()
            messages.success(request, f"Profile for {student.user.get_full_name()} updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")

    return redirect('student_details', pk=student.user.id)


@login_required(login_url="/login/")
def student_profile_update(request, pk):
    if request.method == "POST":
        student = get_object_or_404(Student, id = pk)
        user = student.user


        # Update basic user information
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()

        birth_date = request.POST.get('date_of_birth')
        if birth_date:
            user.date_of_birth = birth_date

        student.school_group = request.POST.get('school_group')
        student.academic_year = request.POST.get('academic_year')

        classroom_id = request.POST.get('classroom')
        if classroom_id:
            student.classroom_id = classroom_id

        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']

        try:
            user.save()
            student.save()
            messages.success(request, f"Profile for {student.user.get_full_name()} updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")

    return redirect('student_details', pk=student.user.id)


