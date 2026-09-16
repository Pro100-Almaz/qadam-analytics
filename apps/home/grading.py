"""Quarter-grade helpers shared by the API, services and reporting.

Extracted from `apps.home.repo.students` so that live code does not depend on
the legacy server-rendered view layer. Pure domain logic — no request, no
template, no permission handling.
"""

from apps.lesson.models import Lesson


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
