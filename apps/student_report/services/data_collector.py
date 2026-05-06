from typing import Optional


def collect_student_data(student_id: int, quarter: int) -> dict:
    from apps.authentication.models import Student
    from apps.home.models import AcademicYear

    student = Student.objects.select_related(
        'user', 'school_group', 'academic_year'
    ).get(pk=student_id)

    academic_year = AcademicYear.objects.filter(is_active=True).first()

    personal = {
        'full_name': student.user.get_full_name() or student.user.username,
        'class_group': str(student.school_group) if student.school_group else '',
        'academic_year': str(academic_year) if academic_year else '',
    }

    grades = _collect_grades(student, academic_year, quarter)
    trends = _compute_trends(grades['subjects'])
    class_context = _collect_class_averages(student, academic_year, quarter)
    psych_states = _collect_psychological_states(student)
    achievements = _collect_achievements(student, academic_year)
    reading = _collect_reading(student, academic_year)
    clubs = _collect_clubs(student, academic_year)

    return {
        'personal': personal,
        'grades': grades,
        'trends': trends,
        'class_context': class_context,
        'psychological_states': psych_states,
        'achievements': achievements,
        'reading': reading,
        'clubs': clubs,
    }


def _collect_grades(student, academic_year, quarter: int) -> dict:
    from apps.home.models import SubjectOffering
    from apps.lesson.models import Lesson
    from apps.lesson.services import get_cached_grades_bulk

    enrollment = student.get_current_enrollment()
    if not enrollment:
        return {
            'subjects': {},
            'total_quarter_grades': {},
            'student_total_grade': 0,
        }

    offerings = list(SubjectOffering.objects.filter(
        class_group=enrollment.class_group,
        academic_year=enrollment.academic_year,
    ).select_related('subject'))

    lessons = list(Lesson.objects.filter(offering__in=offerings))
    grades_map = get_cached_grades_bulk(lessons, [student])

    subjects = {}
    for offering in offerings:
        quarter_grades = {}
        for q in [1, 2, 3, 4]:
            q_lessons = [
                l for l in lessons
                if l.offering_id == offering.id and l.quarter == q
            ]
            if q_lessons:
                lesson_grades = [
                    grades_map.get((l.id, student.id), 0) for l in q_lessons
                ]
                quarter_grades[f'q{q}'] = round(
                    sum(lesson_grades) / len(lesson_grades), 1
                )
            else:
                quarter_grades[f'q{q}'] = None

        graded = [v for v in quarter_grades.values() if v is not None]
        quarter_grades['cumulative'] = (
            round(sum(graded) / len(graded), 1) if graded else None
        )
        subjects[offering.subject.name] = quarter_grades

    from apps.home.repo.students import grade_identifier
    total_quarter_grades = {}
    num_subjects = len(offerings)
    for q in [1, 2, 3, 4]:
        key = f'q{q}'
        vals = [
            subjects[s][key] for s in subjects
            if subjects[s][key] is not None
        ]
        if vals and num_subjects > 0:
            avg = round(sum(vals) / len(vals), 1)
            total_quarter_grades[key] = grade_identifier(avg)
        else:
            total_quarter_grades[key] = None

    cumulatives = [
        subjects[s]['cumulative'] for s in subjects
        if subjects[s]['cumulative'] is not None
    ]
    student_total_grade = (
        round(sum(cumulatives) / len(cumulatives), 1) if cumulatives else 0
    )

    return {
        'subjects': subjects,
        'total_quarter_grades': total_quarter_grades,
        'student_total_grade': student_total_grade,
    }


def _compute_trends(subjects_grades: dict) -> dict:
    trends = {}
    for subject, quarters in subjects_grades.items():
        graded = [
            (q, score) for q, score in sorted(quarters.items())
            if score is not None and q.startswith('q')
        ]
        if len(graded) >= 2:
            prev_score = graded[-2][1]
            curr_score = graded[-1][1]
            change = curr_score - prev_score
            if change > 3:
                direction = 'improving'
            elif change < -3:
                direction = 'declining'
            else:
                direction = 'stable'
            trends[subject] = {'direction': direction, 'change': round(change, 1)}
        else:
            trends[subject] = {'direction': 'insufficient_data', 'change': 0}
    return trends


def _collect_class_averages(student, academic_year, quarter: int) -> dict:
    from apps.home.models import SubjectOffering, Enrollment
    from apps.lesson.models import Lesson
    from apps.lesson.services import get_cached_grades_bulk
    from apps.authentication.models import Student

    enrollment = student.get_current_enrollment()
    if not enrollment:
        return {}

    class_group = enrollment.class_group
    offerings = list(SubjectOffering.objects.filter(
        class_group=class_group,
        academic_year=academic_year,
    ).select_related('subject'))

    if not offerings:
        return {}

    classmate_enrollments = Enrollment.objects.filter(
        class_group=class_group,
        academic_year=academic_year,
        status='active',
    ).select_related('student')

    classmates = [e.student for e in classmate_enrollments]
    if not classmates:
        return {}

    lessons = list(Lesson.objects.filter(
        offering__in=offerings,
        quarter=quarter,
    ))
    if not lessons:
        return {}

    grades_map = get_cached_grades_bulk(lessons, classmates)

    averages = {}
    for offering in offerings:
        o_lessons = [l for l in lessons if l.offering_id == offering.id]
        if not o_lessons:
            continue

        student_avgs = []
        for s in classmates:
            s_grades = [grades_map.get((l.id, s.id), 0) for l in o_lessons]
            avg = sum(s_grades) / len(s_grades)
            student_avgs.append(avg)

        if student_avgs:
            averages[offering.subject.name] = round(
                sum(student_avgs) / len(student_avgs), 1
            )

    return averages


def _collect_psychological_states(student) -> dict:
    from apps.authentication.models import PsychologicalState

    states = list(
        PsychologicalState.objects.filter(student=student)
        .order_by('-time_added')[:20]
        .values('name', 'score', 'comment', 'time_added')
    )

    current = []
    for s in states[:5]:
        current.append({
            'name': s['name'],
            'score': s['score'],
            'comment': s['comment'] or '',
        })

    recent_changes = []
    seen = {}
    for s in states:
        name = s['name']
        if name not in seen:
            seen[name] = s['score']
        elif name not in [r['name'] for r in recent_changes]:
            prev = s['score']
            curr = seen[name]
            change = curr - prev
            if change > 0:
                direction = 'improving'
            elif change < 0:
                direction = 'declining'
            else:
                direction = 'stable'
            recent_changes.append({
                'name': name,
                'previous': prev,
                'current': curr,
                'direction': direction,
            })

    return {'current': current, 'recent_changes': recent_changes}


def _collect_achievements(student, academic_year) -> list:
    from apps.achievement.models import Achievement

    qs = Achievement.objects.filter(student=student)
    if academic_year:
        qs = qs.filter(academic_year=academic_year)

    return list(qs.values(
        'category', 'award_type', 'place', 'role',
        'duration', 'description', 'created_at',
    ))


def _collect_reading(student, academic_year) -> list:
    from apps.achievement.models import ReadingEntry

    qs = ReadingEntry.objects.filter(student=student)
    if academic_year:
        qs = qs.filter(academic_year=academic_year)

    return list(qs.values(
        'title', 'month', 'pages_read', 'test_score', 'created_at',
    ))


def _collect_clubs(student, academic_year) -> list:
    from apps.achievement.models import ClubEntry

    qs = ClubEntry.objects.filter(student=student)
    if academic_year:
        qs = qs.filter(academic_year=academic_year)

    entries = list(qs.values(
        'club_name', 'month', 'plan', 'criteria',
        'total_sessions', 'attended_sessions', 'comments', 'created_at',
    ))

    for entry in entries:
        total = entry.get('total_sessions', 0) or 0
        attended = entry.get('attended_sessions', 0) or 0
        entry['attendance_percentage'] = (
            round(attended / total * 100, 1) if total > 0 else 0
        )

    return entries
