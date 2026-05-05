from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.authentication.models import Teacher, PsychologicalState, Student
from apps.home.models import (
    AcademicYear, SubjectOffering, Enrollment, TeachingAssignment,
    HomeroomTeacherAssignment,
)
from apps.lesson.models import Lesson, TopicGrade
from apps.lesson.services import get_cached_grades_bulk
from apps.home.repo.students import grade_identifier


def _get_active_year():
    return (
        AcademicYear.objects.filter(is_active=True).first()
        or AcademicYear.objects.order_by('-year').first()
    )


def get_lesson_teacher_dashboard(teacher):
    """Dashboard for a lesson/subject teacher: their offerings, lesson counts, grading progress."""
    year = _get_active_year()
    if not year:
        return {'offerings': [], 'summary': {}}

    assignments = TeachingAssignment.objects.filter(
        teacher=teacher,
        offering__academic_year=year,
    ).select_related(
        'offering', 'offering__subject',
        'offering__class_group', 'offering__class_group__grade_level',
    )

    offerings_data = []
    total_lessons = 0
    total_graded = 0
    total_ungraded = 0

    for a in assignments:
        offering = a.offering
        cg = offering.class_group
        lessons = list(Lesson.objects.filter(offering=offering))
        lesson_count = len(lessons)
        total_lessons += lesson_count

        student_count = Enrollment.objects.filter(
            class_group=cg, academic_year=year, status='active',
        ).count()

        graded_count = 0
        for lesson in lessons:
            graded_students = TopicGrade.objects.filter(
                topic__lesson=lesson,
            ).values('student_id').distinct().count()
            if student_count > 0 and graded_students >= student_count:
                graded_count += 1

        total_graded += graded_count
        total_ungraded += (lesson_count - graded_count)

        class_label = f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg)

        offerings_data.append({
            'offering_id': offering.id,
            'subject_name': offering.subject.name,
            'class_group': class_label,
            'role': a.role,
            'lesson_count': lesson_count,
            'student_count': student_count,
            'graded_lessons': graded_count,
            'grading_percentage': round(
                (graded_count / lesson_count * 100) if lesson_count else 0, 1
            ),
        })

    return {
        'offerings': offerings_data,
        'summary': {
            'total_offerings': len(assignments),
            'total_lessons': total_lessons,
            'total_graded': total_graded,
            'total_ungraded': total_ungraded,
            'grading_percentage': round(
                (total_graded / total_lessons * 100) if total_lessons else 0, 1
            ),
        },
    }


def get_homeroom_dashboard(teacher):
    """Dashboard for a homeroom teacher: their class students and cross-subject grades."""
    year = _get_active_year()
    if not year:
        return {'class_group': None, 'students': []}

    assignment = HomeroomTeacherAssignment.objects.filter(
        teacher=teacher, academic_year=year,
    ).select_related('class_group', 'class_group__grade_level').first()

    if not assignment:
        return {'class_group': None, 'students': []}

    cg = assignment.class_group
    class_label = f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg)

    enrollments = Enrollment.objects.filter(
        class_group=cg, academic_year=year, status='active',
    ).select_related('student', 'student__user')

    students = [e.student for e in enrollments]

    offerings = list(SubjectOffering.objects.filter(
        class_group=cg, academic_year=year,
    ).select_related('subject'))

    all_lessons = list(Lesson.objects.filter(offering__in=offerings))
    grades_map = get_cached_grades_bulk(all_lessons, students) if all_lessons and students else {}

    students_data = []
    for student in students:
        subject_grades = []
        total_avg = 0
        subject_count = 0

        for offering in offerings:
            o_lessons = [l for l in all_lessons if l.offering_id == offering.id]
            if not o_lessons:
                subject_grades.append({
                    'subject_name': offering.subject.name,
                    'average': None,
                    'letter_grade': None,
                })
                continue

            avg = sum(
                grades_map.get((l.id, student.id), 0) for l in o_lessons
            ) / len(o_lessons)

            subject_grades.append({
                'subject_name': offering.subject.name,
                'average': round(avg, 1),
                'letter_grade': grade_identifier(avg),
            })
            total_avg += avg
            subject_count += 1

        overall = round(total_avg / subject_count, 1) if subject_count else 0

        psych_latest = PsychologicalState.objects.filter(
            student=student,
        ).order_by('-time_added').first()

        students_data.append({
            'student_id': student.id,
            'user_id': student.user.id,
            'full_name': student.user.get_full_name(),
            'overall_average': overall,
            'overall_letter': grade_identifier(overall) if overall else None,
            'subjects': subject_grades,
            'psychological_state': {
                'name': psych_latest.name,
                'score': psych_latest.score,
                'date': psych_latest.time_added.isoformat() if psych_latest.time_added else None,
            } if psych_latest else None,
        })

    students_data.sort(key=lambda s: s['full_name'])

    return {
        'class_group': class_label,
        'class_group_id': cg.id,
        'student_count': len(students),
        'subject_count': len(offerings),
        'students': students_data,
    }


def get_psychologist_dashboard(user):
    """Dashboard for a psychologist: stats on psychological states across all students."""
    year = _get_active_year()
    if not year:
        return {'stats': {}, 'recent_states': [], 'students_needing_attention': []}

    recent_states = PsychologicalState.objects.select_related(
        'student', 'student__user', 'added_by',
    ).order_by('-time_added')[:20]

    total_states = PsychologicalState.objects.count()
    avg_score = PsychologicalState.objects.aggregate(avg=Avg('score'))['avg'] or 0

    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_count = PsychologicalState.objects.filter(
        time_added__gte=thirty_days_ago,
    ).count()

    score_distribution = {}
    for score in range(1, 6):
        score_distribution[str(score)] = PsychologicalState.objects.filter(
            score=score,
        ).count()

    low_score_students = (
        PsychologicalState.objects.filter(score__lte=2)
        .values('student_id', 'student__user__first_name', 'student__user__last_name')
        .annotate(
            low_count=Count('id'),
            latest_score=Avg('score'),
        )
        .order_by('-low_count')[:10]
    )

    attention_list = []
    for s in low_score_students:
        attention_list.append({
            'student_id': s['student_id'],
            'full_name': f"{s['student__user__first_name']} {s['student__user__last_name']}",
            'low_score_count': s['low_count'],
            'average_score': round(s['latest_score'], 1),
        })

    recent_data = []
    for state in recent_states:
        recent_data.append({
            'id': state.id,
            'student_id': state.student_id,
            'student_name': state.student.user.get_full_name() if state.student else None,
            'name': state.name,
            'score': state.score,
            'comment': state.comment,
            'added_by': state.added_by.get_full_name() if state.added_by else None,
            'time_added': state.time_added.isoformat() if state.time_added else None,
        })

    return {
        'stats': {
            'total_records': total_states,
            'average_score': round(avg_score, 1),
            'records_last_30_days': recent_count,
            'score_distribution': score_distribution,
        },
        'recent_states': recent_data,
        'students_needing_attention': attention_list,
    }


def get_psychologist_student_detail(student_id):
    """Detailed psychological state history for a specific student."""
    student = Student.objects.select_related('user').get(pk=student_id)

    states = PsychologicalState.objects.filter(
        student=student,
    ).select_related('added_by').order_by('-time_added')

    history = []
    for state in states:
        history.append({
            'id': state.id,
            'name': state.name,
            'score': state.score,
            'comment': state.comment,
            'added_by': state.added_by.get_full_name() if state.added_by else None,
            'time_added': state.time_added.isoformat() if state.time_added else None,
        })

    avg_score = states.aggregate(avg=Avg('score'))['avg'] or 0
    total = states.count()

    return {
        'student_id': student.id,
        'full_name': student.user.get_full_name(),
        'total_records': total,
        'average_score': round(avg_score, 1),
        'history': history,
    }


def get_teacher_classes(teacher):
    """Get all class groups a teacher is associated with (via offerings or homeroom)."""
    year = _get_active_year()
    if not year:
        return []

    classes_map = {}

    assignments = TeachingAssignment.objects.filter(
        teacher=teacher,
        offering__academic_year=year,
    ).select_related(
        'offering__class_group',
        'offering__class_group__grade_level',
        'offering__subject',
    )
    for a in assignments:
        cg = a.offering.class_group
        if cg.id not in classes_map:
            label = f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg)
            student_count = Enrollment.objects.filter(
                class_group=cg, academic_year=year, status='active',
            ).count()
            classes_map[cg.id] = {
                'class_group_id': cg.id,
                'display_name': label,
                'grade_level': cg.grade_level.number if cg.grade_level else None,
                'letter': cg.letter,
                'student_count': student_count,
                'subjects': [],
                'is_homeroom': False,
            }
        classes_map[cg.id]['subjects'].append({
            'offering_id': a.offering.id,
            'subject_name': a.offering.subject.name,
            'role': a.role,
        })

    homeroom = HomeroomTeacherAssignment.objects.filter(
        teacher=teacher, academic_year=year,
    ).select_related('class_group', 'class_group__grade_level')
    for h in homeroom:
        cg = h.class_group
        if cg.id in classes_map:
            classes_map[cg.id]['is_homeroom'] = True
        else:
            label = f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg)
            student_count = Enrollment.objects.filter(
                class_group=cg, academic_year=year, status='active',
            ).count()
            classes_map[cg.id] = {
                'class_group_id': cg.id,
                'display_name': label,
                'grade_level': cg.grade_level.number if cg.grade_level else None,
                'letter': cg.letter,
                'student_count': student_count,
                'subjects': [],
                'is_homeroom': True,
            }

    result = sorted(classes_map.values(), key=lambda c: (c['grade_level'] or 0, c['letter']))
    return result


def get_class_students(class_group_id, teacher=None):
    """Get students in a class group with basic grade info."""
    from apps.home.models import ClassGroup

    year = _get_active_year()
    if not year:
        return {'class_group': None, 'students': []}

    cg = ClassGroup.objects.select_related('grade_level').get(pk=class_group_id)
    label = f'{cg.grade_level}{cg.letter}' if cg and cg.grade_level else str(cg)

    enrollments = Enrollment.objects.filter(
        class_group=cg, academic_year=year, status='active',
    ).select_related('student', 'student__user')

    students = [e.student for e in enrollments]

    offerings = list(SubjectOffering.objects.filter(
        class_group=cg, academic_year=year,
    ).select_related('subject'))

    if teacher:
        teacher_offering_ids = set(
            TeachingAssignment.objects.filter(
                teacher=teacher, offering__in=offerings,
            ).values_list('offering_id', flat=True)
        )
        relevant_offerings = [o for o in offerings if o.id in teacher_offering_ids]
    else:
        relevant_offerings = offerings

    all_lessons = list(Lesson.objects.filter(offering__in=relevant_offerings))
    grades_map = get_cached_grades_bulk(all_lessons, students) if all_lessons and students else {}

    students_data = []
    for student in students:
        subject_grades = []
        total_avg = 0
        subject_count = 0

        for offering in relevant_offerings:
            o_lessons = [l for l in all_lessons if l.offering_id == offering.id]
            if not o_lessons:
                subject_grades.append({
                    'offering_id': offering.id,
                    'subject_name': offering.subject.name,
                    'average': None,
                    'letter_grade': None,
                    'lesson_count': 0,
                })
                continue

            avg = sum(
                grades_map.get((l.id, student.id), 0) for l in o_lessons
            ) / len(o_lessons)

            subject_grades.append({
                'offering_id': offering.id,
                'subject_name': offering.subject.name,
                'average': round(avg, 1),
                'letter_grade': grade_identifier(avg),
                'lesson_count': len(o_lessons),
            })
            total_avg += avg
            subject_count += 1

        overall = round(total_avg / subject_count, 1) if subject_count else 0

        psych_latest = PsychologicalState.objects.filter(
            student=student,
        ).order_by('-time_added').first()

        students_data.append({
            'student_id': student.id,
            'user_id': student.user.id,
            'full_name': student.user.get_full_name(),
            'avatar': student.user.avatar.url if student.user.avatar else None,
            'overall_average': overall,
            'overall_letter': grade_identifier(overall) if overall else None,
            'subjects': subject_grades,
            'psychological_state': {
                'name': psych_latest.name,
                'score': psych_latest.score,
            } if psych_latest else None,
        })

    students_data.sort(key=lambda s: s['full_name'])

    return {
        'class_group_id': cg.id,
        'class_group': label,
        'student_count': len(students),
        'subject_count': len(relevant_offerings),
        'students': students_data,
    }
