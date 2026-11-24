"""
Queries behind the student overview (spec 0019). Each returns plain numbers.
The rules that turn them into a payload live in apps/home/services.py.
"""
from collections import defaultdict
from statistics import mean

from django.db.models import Count, Exists, OuterRef, Q

from apps.authentication.models import PsychologicalState
from apps.home.models import Enrollment, QuarterGrade
from apps.lesson.models import Homework, HomeworkGrade, ScheduleAttendance


def class_quarter_averages(cohort_ids):
    """
    {quarter: mean of the per-student quarter averages} over `cohort_ids`.

    Each student's marks are restricted to offerings of class groups they are
    actively enrolled in this year, the same rule compute_child_grades uses for
    one student. Rows a departed student left behind on the class's offerings
    therefore do not count (AC-8). Students with no marks in a quarter sit it
    out. One query.
    """
    enrolled_in_offering_class = Enrollment.objects.filter(
        student=OuterRef('student'),
        class_group=OuterRef('offering__class_group'),
        status='active',
        class_group__academic_year__is_active=True,
    )
    marks = defaultdict(lambda: defaultdict(list))
    for student_id, quarter, grade in QuarterGrade.objects.filter(
        student_id__in=cohort_ids,
    ).filter(Exists(enrolled_in_offering_class)).values_list(
        'student_id', 'quarter', 'grade',
    ):
        marks[quarter][student_id].append(grade)
    return {
        q: round(mean(mean(g) for g in marks[q].values()), 1) if marks[q] else None
        for q in (1, 2, 3, 4)
    }


def subject_quarter_grades(student, offerings, quarters):
    """{(offering_id, quarter): grade} for the student's own marks."""
    return {
        (offering_id, quarter): grade
        for offering_id, quarter, grade in QuarterGrade.objects.filter(
            student=student, offering__in=offerings, quarter__in=quarters,
        ).values_list('offering_id', 'quarter', 'grade')
    }


def attendance_counts(student_ids, quarter):
    """Pooled present / absent over `student_ids` for the quarter's schedules."""
    return ScheduleAttendance.objects.filter(
        student_id__in=student_ids, session__schedule__quarter=quarter,
    ).aggregate(
        present=Count('id', filter=Q(status='present')),
        absent=Count('id', filter=Q(status='absent')),
    )


def attendance_days(student, quarter):
    """[(date, recorded, absent)] per recorded day of the quarter, oldest first."""
    return list(ScheduleAttendance.objects.filter(
        student=student, session__schedule__quarter=quarter,
    ).values('date').annotate(
        recorded=Count('id'),
        absent=Count('id', filter=Q(status='absent')),
    ).order_by('date').values_list('date', 'recorded', 'absent'))


def homework_counts(student, offerings, quarter, today):
    """
    submitted / overdue / pending for the quarter's active homework. There is
    no submission model, so a homework the student holds a grade for counts as
    submitted (spec 0019).
    """
    graded = Exists(HomeworkGrade.objects.filter(
        homework=OuterRef('pk'), student=student, grade__isnull=False,
    ))
    return Homework.objects.filter(
        offering__in=offerings, is_active=True, quarter=quarter,
    ).annotate(graded=graded).aggregate(
        submitted=Count('id', filter=Q(graded=True)),
        overdue=Count('id', filter=Q(graded=False, due_date__lt=today)),
        pending=Count('id', filter=Q(graded=False) & (
            Q(due_date__gte=today) | Q(due_date__isnull=True)
        )),
    )


def latest_psychological_state(student):
    return PsychologicalState.objects.filter(
        student=student,
    ).order_by('-time_added', '-id').first()
