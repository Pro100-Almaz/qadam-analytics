from datetime import timedelta

from django.utils import timezone

from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import (
    AcademicYear, SubjectOffering, Enrollment, TeachingAssignment,
)
from apps.lesson.models import Lesson, TopicGrade
from apps.lesson.services import get_cached_grades_bulk
from apps.home.repo.students import grade_identifier
from core.permissions import is_staff_role


def get_dashboard_stats():
    from apps.home.models import ClassGroup
    return {
        'total_students': Student.objects.count(),
        'total_teachers': Teacher.objects.count(),
        'total_classes': ClassGroup.objects.count(),
    }


def get_students_for_role(user, year_id=None, class_group_id=None):
    from core.permissions import is_admin_role, is_teacher_role

    if user.is_student():
        try:
            student = Student.objects.select_related('user').get(user=user)
            enrollment = Enrollment.objects.filter(
                student=student, status='active',
            ).select_related('class_group').first()
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
                enrollment = Enrollment.objects.filter(
                    student=child, status='active',
                ).select_related('class_group').first()
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
        academic_year_id=year_id, status='active'
    ).select_related('student', 'student__user', 'class_group')

    if class_group_id:
        enrollments = enrollments.filter(class_group_id=class_group_id)

    students = []
    for e in enrollments:
        e.student.classroom = e.class_group
        students.append(e.student)
    return students


def compute_child_grades(student, enrollment):
    """Compute grade summaries for a student — used by parent endpoints."""
    offerings = list(SubjectOffering.objects.filter(
        class_group=enrollment.class_group,
        academic_year=enrollment.academic_year,
    ).select_related('subject'))

    lessons = list(Lesson.objects.filter(offering__in=offerings))
    grades_map = get_cached_grades_bulk(lessons, [student])

    quarter_grades = {}
    cumulative_total = 0
    active_quarters = 0

    for q in (1, 2, 3, 4):
        q_sum = 0
        q_count = 0
        for offering in offerings:
            q_lessons = [l for l in lessons if l.offering_id == offering.id and l.quarter == q]
            if q_lessons:
                avg = sum(grades_map.get((l.id, student.id), 0) for l in q_lessons) / len(q_lessons)
                q_sum += avg
                q_count += 1
        if q_count:
            q_avg = q_sum / q_count
            quarter_grades[str(q)] = grade_identifier(q_avg)
            cumulative_total += q_avg
            active_quarters += 1
        else:
            quarter_grades[str(q)] = None

    student_total_grade = round(cumulative_total / active_quarters, 1) if active_quarters else 0

    subject_data = []
    for offering in offerings:
        offering_lessons = [l for l in lessons if l.offering_id == offering.id]
        subj_quarter_grades = {}
        subj_cumulative = 0
        subj_active = 0
        for q in (1, 2, 3, 4):
            q_lessons = [l for l in offering_lessons if l.quarter == q]
            if q_lessons:
                avg = sum(grades_map.get((l.id, student.id), 0) for l in q_lessons) / len(q_lessons)
                subj_quarter_grades[str(q)] = grade_identifier(avg)
                subj_cumulative += avg
                subj_active += 1
            else:
                subj_quarter_grades[str(q)] = None

        subject_data.append({
            'offering_id': offering.id,
            'subject_id': offering.subject_id,
            'subject_name': offering.subject.name,
            'language': offering.subject.language_group,
            'student_grade': round(subj_cumulative / subj_active, 1) if subj_active else 0,
            'quarter_grades': subj_quarter_grades,
        })

    return student_total_grade, quarter_grades, subject_data


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
            subject=subject, academic_year=current_year
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
        academic_year=current_year,
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
        teacher=teacher,
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
            academic_year=a.offering.academic_year,
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
