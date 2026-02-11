from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect

from apps.home.component_functions.show_alert_modal import show_alert_modal
from core.decorators import role_required
from core.permissions import can_access_student, permission_denied_response
from apps.authentication.forms import UserUpdateForm
from apps.home.models import AcademicYear, ClassGroup, Enrollment
from apps.authentication.models import PsychologicalStateTemplates, PsychologicalState, Student
from apps.lesson.models import Lesson


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def classes(request):
    return render(request, 'home/classes.html')


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal')
def students_list(request):
    selected_class = request.GET.get('class', 'all')
    selected_year = request.GET.get('year')

    # Get years for filter
    years = AcademicYear.objects.order_by('-year')
    if not selected_year and years.exists():
        selected_year = str(years.first().id)

    # Filter students via Enrollment
    if selected_year:
        enrollments = Enrollment.objects.filter(
            academic_year_id=selected_year,
            status='active'
        ).select_related('student', 'student__user', 'class_group')

        if selected_class != 'all':
            enrollments = enrollments.filter(class_group__name=selected_class)

        students = []
        for e in enrollments:
            e.student.classroom = e.class_group
            students.append(e.student)
    else:
        students = list(Student.objects.all())

    # Get class groups for filter dropdown
    class_groups = ClassGroup.objects.filter(academic_year_id=selected_year) if selected_year else ClassGroup.objects.all()

    page = request.GET.get('page')
    paginator = Paginator(students, 10)
    page_obj = paginator.get_page(page)

    context = {
        'students': students,
        'page_obj': page_obj,
        'selected_class': selected_class,
        'classrooms': class_groups,
        'years': years,
        'selected_year': int(selected_year) if selected_year else None,
    }
    return render(request, 'home/students.html', context)


def calculate_quarter_grade(quarter, offering, student, grades_map=None):
    """
    Calculate student's grade for a specific quarter in an offering.

    Args:
        quarter: Quarter number (1-4)
        offering: SubjectOffering instance
        student: Student instance
        grades_map: Optional dict mapping (lesson_id, student_id) -> grade.
                   If provided, uses this instead of querying the database.
    """
    lessons = Lesson.objects.filter(offering=offering, quarter=quarter)
    lesson_quarter_grades = []

    if grades_map is not None:
        # Use pre-fetched grades
        for lesson in lessons:
            grade = grades_map.get((lesson.id, student.id), 0)
            lesson_quarter_grades.append(round(grade, 1))
    else:
        # Fallback: fetch grades for this student and these lessons in one query
        from apps.lesson.models import TopicGrade, Topic
        lesson_ids = list(lessons.values_list('id', flat=True))
        topic_grades = TopicGrade.objects.filter(
            topic__lesson_id__in=lesson_ids,
            student=student
        ).values('topic_id', 'topic__lesson_id', 'grade')

        local_grades_map = {}
        for tg in topic_grades:
            local_grades_map[(tg['topic_id'], student.id)] = tg['grade']

        # Get parent topics with weights
        parent_topics = Topic.objects.filter(
            lesson_id__in=lesson_ids,
            parent__isnull=True
        ).values('id', 'lesson_id', 'weight')

        topics_by_lesson = {}
        for t in parent_topics:
            if t['lesson_id'] not in topics_by_lesson:
                topics_by_lesson[t['lesson_id']] = []
            topics_by_lesson[t['lesson_id']].append(t)

        for lesson in lessons:
            total_grade = 0
            for topic in topics_by_lesson.get(lesson.id, []):
                grade = local_grades_map.get((topic['id'], student.id), 0)
                total_grade += grade * (float(topic['weight']) / 100)
            lesson_quarter_grades.append(round(total_grade, 1))

    try:
        subject_quarter_grade = sum(lesson_quarter_grades) / len(lesson_quarter_grades)
        return subject_quarter_grade
    except ZeroDivisionError:
        return 0


def grade_identifier(percent):
    """Convert percentage to grade (2-5 scale)."""
    if percent > 80:
        return 5
    elif percent > 60:
        return 4
    elif percent > 40:
        return 3
    else:
        return 2


@role_required('teacher', 'admin', 'supervisor', 'homeroom_teacher', 'principal', 'parent', 'student')
def student_details(request, pk):
    student = get_object_or_404(Student, user_id=pk)

    # Object-level permission check
    if not can_access_student(request.user, student):
        message = "Вы не можете просмотреть профиль данного ученика! Он(а) не является участником вашего класса."
        if request.headers.get('x-requested-with') == "XMLHttpRequest":
            return show_alert_modal(request, message)
        return redirect('home/students.html')

    # Get student's current enrollment and class group
    current_enrollment = student.get_current_enrollment()
    current_class_group = current_enrollment.class_group if current_enrollment else None

    # Get offerings for the student's class
    from apps.home.models import SubjectOffering
    from apps.lesson.models import TopicGrade, Topic
    offerings = []
    if current_enrollment:
        offerings = list(SubjectOffering.objects.filter(
            class_group=current_class_group,
            academic_year=current_enrollment.academic_year
        ).select_related('subject'))

    # Get lessons for these offerings
    lessons = list(Lesson.objects.filter(offering__in=offerings))

    templates = PsychologicalStateTemplates.objects.all()
    psychological_states = PsychologicalState.objects.filter(student_id=student.id)
    last_state = psychological_states.last()
    last_updated = last_state.time_added if last_state else None

    # Bulk fetch all grades for this student across all lessons (single query)
    grades_map = Lesson.calculate_grades_bulk(lessons, [student]) if lessons else {}

    # Calculate grades per quarter per subject using bulk-fetched data
    subject_quarter_grades = {}
    for quarter in [1, 2, 3, 4]:
        subject_quarter_grades[quarter] = {}
        for offering in offerings:
            quarter_lessons = [l for l in lessons if l.offering_id == offering.id and l.quarter == quarter]
            if quarter_lessons:
                lesson_grades = [grades_map.get((l.id, student.id), 0) for l in quarter_lessons]
                grade = sum(lesson_grades) / len(lesson_grades)
            else:
                grade = 0
            subject_quarter_grades[quarter][offering.subject.name] = grade if grade is not None else 0

    # Calculate total quarter grades
    total_quarter_grades = {}
    num_subjects = len(offerings)
    student_total_grade = 0

    for quarter in [1, 2, 3, 4]:
        quarter_sum = sum(subject_quarter_grades[quarter].values())
        avg = round(quarter_sum / num_subjects, 1) if num_subjects > 0 else 0
        student_total_grade += round(avg / 4, 1)
        total_quarter_grades[quarter] = grade_identifier(avg)

    # Calculate cumulative subject grades
    cumulative_subject_grades = {}
    for offering in offerings:
        total = sum(subject_quarter_grades[q].get(offering.subject.name, 0) for q in [1, 2, 3, 4])
        cumulative_subject_grades[offering.subject.name] = round(total / 4, 1)

    academic_years = AcademicYear.objects.all()

    context = {
        'student_total_grade': student_total_grade,
        'total_quarter_grades': total_quarter_grades,
        'cumulative_subject_grades': cumulative_subject_grades,
        'subject_quarter_grades': list(subject_quarter_grades.items()),
        'academic_years': academic_years,
        'student': student,
        'current_class_group': current_class_group,
        'offerings': offerings,
        'subjects': [o.subject for o in offerings],
        'total_subjects': len(offerings),
        'lessons': lessons,
        'templates': templates,
        'psychological_states': psychological_states,
        'last_updated': last_updated,
    }
    return render(request, 'home/student_details.html', context)


@role_required('admin', 'supervisor')
def student_profile_update(request, pk):
    if request.method == "POST":
        student = get_object_or_404(Student, id=pk)
        user = student.user

        # Update basic user information
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()

        birth_date = request.POST.get('date_of_birth')
        if birth_date:
            user.date_of_birth = birth_date

        # Update school group if provided
        school_group_id = request.POST.get('school_group')
        if school_group_id:
            from apps.authentication.models import SchoolGroup
            try:
                student.school_group = SchoolGroup.objects.get(id=school_group_id)
            except SchoolGroup.DoesNotExist:
                pass

        # Update academic year if provided
        academic_year_id = request.POST.get('academic_year')
        if academic_year_id:
            try:
                student.academic_year = AcademicYear.objects.get(id=academic_year_id)
            except AcademicYear.DoesNotExist:
                pass

        # Handle class group change via Enrollment
        class_group_id = request.POST.get('class_group')
        if class_group_id:
            try:
                class_group = ClassGroup.objects.get(id=class_group_id)
                academic_year = student.academic_year or AcademicYear.objects.filter(is_active=True).first()
                if academic_year:
                    Enrollment.enroll_student(student, class_group, academic_year)
            except ClassGroup.DoesNotExist:
                pass

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


def get_student(student_id : int):
    return Student.objects.get(id=student_id)

def get_all_students():
    return Student.objects.all()