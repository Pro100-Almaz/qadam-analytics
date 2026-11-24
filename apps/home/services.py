from datetime import timedelta

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import (
    AcademicYear, ClassGroup, SubjectOffering, Enrollment, TeachingAssignment,
    QuarterGrade,
)
from apps.lesson.models import Lesson, TopicGrade
from apps.lesson.services import get_cached_grades_bulk
from core.permissions import is_staff_role


def get_dashboard_stats():
    from apps.home.models import ClassGroup
    return {
        'total_students': Student.objects.count(),
        'total_teachers': Teacher.objects.count(),
        'total_classes': ClassGroup.objects.count(),
    }


# A student holds at most one active enrollment in a major class group but any
# number of minor (подгруппа) ones, so the major enrollment is the one that
# says which class the student is in.
MAJOR_GROUP_FIRST = Case(
    When(class_group__category=ClassGroup.MAJOR_CHOICE, then=Value(0)),
    default=Value(1),
    output_field=IntegerField(),
)


def _primary_enrollment(student):
    """The student's active enrollment, preferring their major class group."""
    return (
        Enrollment.objects
        .filter(student=student, status='active')
        .select_related('class_group')
        .annotate(major_group_first=MAJOR_GROUP_FIRST)
        .order_by('major_group_first', '-class_group__academic_year__year')
        .first()
    )


def get_students_for_role(user, year_id=None, class_group_id=None):
    from core.permissions import is_admin_role, is_teacher_role

    if user.is_student():
        try:
            student = Student.objects.select_related('user').get(user=user)
            enrollment = _primary_enrollment(student)
            if enrollment:
                student.classroom = enrollment.class_group
                return [student]
            return []
        except Student.DoesNotExist:
            return []

    if user.is_parent():
        try:
            parent = Parent.objects.get(user=user)
            children = parent.students.select_related('user').all()
            result = []
            for child in children:
                enrollment = _primary_enrollment(child)
                if enrollment:
                    child.classroom = enrollment.class_group
                    result.append(child)
            return result
        except Parent.DoesNotExist:
            return []

    if not (is_admin_role(user) or is_teacher_role(user) or is_staff_role(user)):
        return []

    if not year_id:
        latest = AcademicYear.objects.order_by('-year').first()
        year_id = latest.id if latest else None
    if not year_id:
        return []

    enrollments = Enrollment.objects.filter(
        class_group__academic_year_id=year_id, status='active'
    ).select_related('student', 'student__user', 'class_group')

    if class_group_id:
        enrollments = enrollments.filter(class_group_id=class_group_id)

    # Major groups first, so a student enrolled in подгруппы as well as their
    # class is listed once, under their class.
    enrollments = enrollments.annotate(
        major_group_first=MAJOR_GROUP_FIRST,
    ).order_by('major_group_first', 'class_group_id', 'student_id')

    students = []
    seen = set()
    for e in enrollments:
        if e.student_id in seen:
            continue
        seen.add(e.student_id)
        e.student.classroom = e.class_group
        students.append(e.student)
    return students


def current_offerings(student):
    """
    The offerings of every class group the student is in this year: their
    major class plus any minor ones (подгруппы), whose subjects are taught
    only there.
    """
    enrollments = list(student.get_current_minor_enrollments())
    major = student.get_current_enrollment()
    if major:
        enrollments.insert(0, major)
    return list(SubjectOffering.objects.filter(
        class_group_id__in=[e.class_group_id for e in enrollments],
    ).select_related('subject').order_by('class_group__category', 'id'))


def compute_child_grades(student):
    """
    Quarter and total grades for a child on the parent endpoints.

    Read from the quarter marks teachers entered (`QuarterGrade`, spec 0008),
    as the student detail payload is, not derived from topic grades. Covers
    the offerings of the child's major and minor class groups. A subject
    without a mark is left out of the average rather than counted as 0, and a
    quarter (or year) with no marks at all is None.
    """
    offerings = current_offerings(student)
    marks_by_quarter = {q: [] for q in (1, 2, 3, 4)}
    for quarter, grade in QuarterGrade.objects.filter(
        student=student, offering__in=offerings,
    ).values_list('quarter', 'grade'):
        marks_by_quarter[quarter].append(grade)

    def average(values, digits):
        return round(sum(values) / len(values), digits) if values else None

    quarter_grades = {
        str(q): average(marks, 1) for q, marks in marks_by_quarter.items()
    }
    student_total_grade = average(
        [g for g in quarter_grades.values() if g is not None], 2,
    )
    return student_total_grade, quarter_grades


def get_subject_grades(subject, user, quarter=1, class_group_id=0):
    """Compute grade data for a subject's grades page."""
    from core.permissions import can_access_subject

    if not can_access_subject(user, subject):
        return None

    current_year = AcademicYear.objects.filter(is_active=True).first()
    if not current_year:
        current_year = AcademicYear.objects.order_by('-year').first()

    offerings = list(
        SubjectOffering.objects.filter(
            subject=subject, class_group__academic_year=current_year
        ).select_related('class_group')
    ) if current_year else []

    if not offerings:
        return {
            'quarter': quarter,
            'students_count': 0,
            'lessons_count': 0,
            'average_subject_points': 0,
            'completion_percent': 0,
            'top_grades': [],
            'lessons': [],
            'lesson_avgs': {},
        }

    class_group_ids = [o.class_group_id for o in offerings]
    enrollments = Enrollment.objects.filter(
        class_group_id__in=class_group_ids,
        class_group__academic_year=current_year,
        status='active',
    ).select_related('student', 'student__user')

    students_by_id = {}
    for e in enrollments:
        students_by_id[e.student.id] = e.student
    students = list(students_by_id.values())

    total_lessons = list(
        Lesson.objects.filter(offering__in=offerings)
        .select_related('offering', 'offering__class_group')
    )
    quarter_lessons = sorted(
        [
            l for l in total_lessons
            if l.quarter == quarter and
               (not class_group_id or l.offering.class_group_id == class_group_id)
         ],
        key=lambda x: x.created_at,
    )

    all_grades_map = get_cached_grades_bulk(total_lessons, students)

    lesson_avgs = {}
    for lesson in quarter_lessons:
        lesson_avgs[lesson.id] = {
            student.id: round(all_grades_map.get((lesson.id, student.id), 0), 1)
            for student in students
        }

    total_lesson_count = len(total_lessons)
    quarter_lesson_count = len(quarter_lessons)
    student_grades = {}
    total_student_grades = {}

    for student in students:
        total_grade = sum(
            all_grades_map.get((l.id, student.id), 0) for l in total_lessons
        )
        quarter_grade = sum(
            all_grades_map.get((l.id, student.id), 0) for l in quarter_lessons
        )

        avg_quarter = quarter_grade / quarter_lesson_count if quarter_lesson_count else 0
        avg_total = total_grade / total_lesson_count if total_lesson_count else 0

        student_grades[student.id] = {
            'grade': round(avg_quarter, 1),
            'student_name': student.user.get_full_name(),
            'student_id': student.id,
            'user_id': student.user.id,
        }
        total_student_grades[student.id] = round(avg_total, 1)

    top_grades = sorted(
        student_grades.values(), key=lambda x: x['grade'], reverse=True
    )

    students_count = len(students)
    avg_points = (
        round(sum(s['grade'] for s in student_grades.values()) / students_count, 1)
        if students_count else 0
    )
    graded = sum(1 for g in total_student_grades.values() if g > 0)
    completion = round((graded / students_count) * 100, 1) if students_count else 0

    lessons_data = [
        {
            'id': l.id,
            'title': l.title,
            'date': l.date,
            'order': l.order,
            'class_group_name': str(l.offering.class_group)
        }
        for l in quarter_lessons
    ]

    return {
        'quarter': quarter,
        'students_count': students_count,
        'lessons_count': total_lesson_count,
        'average_subject_points': avg_points,
        'completion_percent': completion,
        'top_grades': top_grades,
        'lessons': lessons_data,
        'lesson_avgs': {
            str(lid): {str(sid): g for sid, g in smap.items()}
            for lid, smap in lesson_avgs.items()
        },
    }


def get_teacher_workload(teacher, week_start=None, week_end=None):
    now = timezone.now().date()
    if not week_start:
        week_start = now - timedelta(days=now.weekday())
    if not week_end:
        week_end = week_start + timedelta(days=6)

    assignments = TeachingAssignment.objects.filter(
        teacher=teacher, quarter__isnull=False,
    ).select_related('offering', 'offering__subject', 'offering__class_group',
                     'offering__class_group__grade_level')

    offering_ids = [a.offering_id for a in assignments]

    all_lessons = list(Lesson.objects.filter(
        offering_id__in=offering_ids,
    ).select_related('offering'))

    week_lessons = [l for l in all_lessons if l.date and week_start <= l.date <= week_end]
    taught = [l for l in week_lessons if l.date <= now]
    upcoming = [l for l in week_lessons if l.date > now]

    without_topics = sum(
        1 for l in week_lessons if not l.topics.filter(parent__isnull=True).exists()
    )

    lesson_ids = [l.id for l in week_lessons]
    graded_lessons = set(
        TopicGrade.objects.filter(
            topic__lesson_id__in=lesson_ids,
        ).values_list('topic__lesson_id', flat=True).distinct()
    )

    enrollment_counts = {}
    for a in assignments:
        count = Enrollment.objects.filter(
            class_group=a.offering.class_group,
            class_group__academic_year_id=a.offering.academic_year_id,
            status='active',
        ).count()
        enrollment_counts[a.offering_id] = count

    fully_graded = 0
    partially_graded = 0
    ungraded = 0
    for l in week_lessons:
        if l.id not in graded_lessons:
            ungraded += 1
            continue
        expected = enrollment_counts.get(l.offering_id, 0)
        if expected == 0:
            fully_graded += 1
            continue
        actual = TopicGrade.objects.filter(
            topic__lesson_id=l.id,
        ).values('student_id').distinct().count()
        if actual >= expected:
            fully_graded += 1
        else:
            partially_graded += 1

    total_to_grade = len(week_lessons)
    completion_pct = round(
        (fully_graded / total_to_grade) * 100, 1
    ) if total_to_grade else 0

    subjects = []
    for a in assignments:
        offering = a.offering
        subj_lessons = [l for l in week_lessons if l.offering_id == offering.id]
        subj_grading_complete = all(
            l.id in graded_lessons for l in subj_lessons
        ) if subj_lessons else True
        cg = offering.class_group
        subjects.append({
            'subject_name': offering.subject.name,
            'class_group': f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg),
            'lessons_this_week': len(subj_lessons),
            'grading_complete': subj_grading_complete,
        })

    return {
        'teacher_id': teacher.id,
        'period': f'{week_start} to {week_end}',
        'lessons_taught': len(taught),
        'lessons_upcoming': len(upcoming),
        'lessons_without_topics': without_topics,
        'grading_completion': {
            'total_lessons_to_grade': total_to_grade,
            'fully_graded': fully_graded,
            'partially_graded': partially_graded,
            'ungraded': ungraded,
            'completion_percentage': completion_pct,
        },
        'subjects': subjects,
    }


# ── Student overview (spec 0019) ──

SEVERITY_ORDER = {'critical': 0, 'warning': 1}


def resolve_quarter(academic_year, requested=None, today=None):
    """
    The quarter the overview reports on. `requested` wins. Otherwise the
    current quarter; between quarters the last one that has ended; else 1.
    """
    if requested:
        return requested
    if academic_year is None:
        return 1
    today = today or timezone.localdate()
    current = academic_year.quarter_of(today)
    if current:
        return current
    ended = [
        q for q in (1, 2, 3, 4)
        if getattr(academic_year, f'q{q}_end')
        and getattr(academic_year, f'q{q}_end') < today
    ]
    return max(ended) if ended else 1


def absence_streak(days):
    """
    Absent days in a row, ending at the most recent recorded day. A day is
    absent when every slot recorded on it is. `days` is [(date, recorded,
    absent)] oldest first; days with no record are simply not in it.
    """
    streak = 0
    for _, recorded, absent in reversed(days):
        if absent != recorded:
            break
        streak += 1
    return streak


def _flag(code, severity, params, subject=None):
    return {
        'code': code,
        'severity': severity,
        'subject_id': subject['subject_id'] if subject else None,
        'subject_name': subject['subject_name'] if subject else None,
        'params': params,
    }


def attention_flags(metrics, thresholds):
    """
    The overview's attention list from already-computed numbers. Pure, so
    the thresholds can be tested without a database.

    metrics: {
        'subjects': [{subject_id, subject_name, grade, previous_grade}],
        'absence_streak': int,
        'attendance_rate': float | None,
        'overdue_homework': int,
        'wellbeing': {'name', 'score'} | None,
    }
    """
    t = thresholds
    flags = []

    for subject in metrics['subjects']:
        grade, previous = subject['grade'], subject['previous_grade']
        if grade is None:
            continue
        if grade <= t['low_grade']['critical']:
            flags.append(_flag('low_grade', 'critical', {'grade': grade}, subject))
        if previous is not None and previous - grade >= t['falling_grade']['warning']:
            flags.append(_flag(
                'falling_grade', 'warning', {'from': previous, 'to': grade}, subject,
            ))

    streak = metrics['absence_streak']
    if streak >= t['absence_streak']['critical']:
        flags.append(_flag('absence_streak', 'critical', {'days': streak}))
    elif streak >= t['absence_streak']['warning']:
        flags.append(_flag('absence_streak', 'warning', {'days': streak}))

    rate = metrics['attendance_rate']
    if rate is not None:
        if rate < t['low_attendance']['critical']:
            flags.append(_flag('low_attendance', 'critical', {'rate': rate}))
        elif rate < t['low_attendance']['warning']:
            flags.append(_flag('low_attendance', 'warning', {'rate': rate}))

    overdue = metrics['overdue_homework']
    if overdue >= t['overdue_homework']['warning']:
        flags.append(_flag('overdue_homework', 'warning', {'count': overdue}))

    wellbeing = metrics['wellbeing']
    if wellbeing and wellbeing['score'] <= t['wellbeing_drop']['warning']:
        flags.append(_flag(
            'wellbeing_drop', 'warning',
            {'score': wellbeing['score'], 'name': wellbeing['name']},
        ))

    return sorted(flags, key=lambda f: (
        SEVERITY_ORDER[f['severity']], f['code'], f['subject_name'] or '',
    ))


def _rate(counts):
    registered = counts['present'] + counts['absent']
    return round(100 * counts['present'] / registered, 1) if registered else None


def build_student_overview(student, quarter=None):
    """The payload of GET students/<user_id>/overview/ (spec 0019)."""
    from django.conf import settings

    from apps.home.repo import student_overview as repo
    from apps.lesson.api.analytics_common import enrolled_students

    academic_year = AcademicYear.objects.filter(is_active=True).first()
    quarter = resolve_quarter(academic_year, quarter)
    previous = quarter - 1 if quarter > 1 else None
    today = timezone.localdate()

    offerings = current_offerings(student)
    # All four quarters in one query: the per-quarter averages follow
    # compute_child_grades (unmarked subjects skipped), and the attention
    # flags read the selected and previous quarter from the same rows.
    grades = repo.subject_quarter_grades(student, offerings, (1, 2, 3, 4))
    own = {}
    for q in (1, 2, 3, 4):
        marks = [g for (_, gq), g in grades.items() if gq == q]
        own[q] = round(sum(marks) / len(marks), 1) if marks else None
    enrollment = student.get_current_enrollment()
    cohort_ids = [
        s.id for s in enrolled_students(enrollment.class_group_id, academic_year.id)
    ] if enrollment and academic_year else []
    class_avg = (
        repo.class_quarter_averages(cohort_ids) if cohort_ids
        else dict.fromkeys((1, 2, 3, 4))
    )

    own_attendance = repo.attendance_counts([student.id], quarter)
    class_attendance = (
        repo.attendance_counts(cohort_ids, quarter) if cohort_ids
        else {'present': 0, 'absent': 0}
    )
    attendance_rate = _rate(own_attendance)
    homework = repo.homework_counts(student, offerings, quarter, today)
    latest = repo.latest_psychological_state(student)
    wellbeing = {
        'name': latest.name,
        'score': latest.score,
        'time_added': latest.time_added.isoformat() if latest.time_added else None,
    } if latest else None

    subjects = [
        {
            'subject_id': o.subject_id,
            'subject_name': o.subject.name,
            'grade': grades.get((o.id, quarter)),
            'previous_grade': grades.get((o.id, previous)) if previous else None,
        }
        for o in offerings
    ]
    thresholds = settings.STUDENT_ATTENTION_THRESHOLDS

    return {
        'student_id': student.user_id,
        'quarter': quarter,
        'grades': {
            'average': own[quarter],
            'class_average': class_avg[quarter],
            'previous_quarter_average': own[previous] if previous else None,
            'by_quarter': [
                {'quarter': q, 'average': own[q], 'class_average': class_avg[q]}
                for q in (1, 2, 3, 4)
            ],
        },
        'attendance': {
            'rate': attendance_rate,
            'class_rate': _rate(class_attendance),
            'present': own_attendance['present'],
            # ScheduleAttendance has no late status (spec 0019).
            'late': 0,
            'absent': own_attendance['absent'],
            'total': own_attendance['present'] + own_attendance['absent'],
        },
        'homework': {**homework, 'total': sum(homework.values())},
        'wellbeing': {'latest': wellbeing},
        'attention': attention_flags({
            'subjects': subjects,
            'absence_streak': absence_streak(repo.attendance_days(student, quarter)),
            'attendance_rate': attendance_rate,
            'overdue_homework': homework['overdue'],
            'wellbeing': wellbeing,
        }, thresholds),
    }
