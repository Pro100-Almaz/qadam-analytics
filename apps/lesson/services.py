from django.core.cache import cache

from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import SubjectOffering, Enrollment, TeachingAssignment
from apps.lesson.models import Lesson, Topic, TopicGrade, MergedLessonComment, QuarterGradeSnapshot
from core.permissions import is_admin_role, is_teacher_role

GRADE_CACHE_TTL = 300


def invalidate_lesson_grade_cache(lesson_id):
    cache.delete(f'grades:lesson:{lesson_id}')


def get_cached_grades_bulk(lessons, students):
    if not lessons:
        return {}
    uncached_lessons = []
    cached_results = {}

    for lesson in lessons:
        key = f'grades:lesson:{lesson.id}'
        cached = cache.get(key)
        if cached is not None:
            for student in students:
                grade = cached.get(student.id, 0)
                cached_results[(lesson.id, student.id)] = grade
        else:
            uncached_lessons.append(lesson)

    if uncached_lessons:
        fresh = Lesson.calculate_grades_bulk(uncached_lessons, students)
        cached_results.update(fresh)

        for lesson in uncached_lessons:
            lesson_grades = {
                s.id: fresh.get((lesson.id, s.id), 0) for s in students
            }
            cache.set(f'grades:lesson:{lesson.id}', lesson_grades, GRADE_CACHE_TTL)

    return cached_results


def get_available_offerings(user):
    """Return the SubjectOffering queryset available to the requesting user."""
    if is_admin_role(user):
        return SubjectOffering.objects.select_related(
            'subject', 'class_group', 'academic_year'
        )
    if is_teacher_role(user):
        try:
            teacher = Teacher.objects.get(user=user)
            offering_ids = TeachingAssignment.objects.filter(
                teacher=teacher
            ).values_list('offering_id', flat=True)
            return SubjectOffering.objects.filter(
                id__in=offering_ids
            ).select_related('subject', 'class_group', 'academic_year')
        except Teacher.DoesNotExist:
            return SubjectOffering.objects.none()
    return SubjectOffering.objects.none()


def build_graded_percent_map(lessons):
    """Build {lesson_id: percent} for a list of lessons in bulk."""
    from django.db.models import Count

    lesson_ids = [l.id for l in lessons]
    offering_ids = list({l.offering_id for l in lessons if l.offering_id})

    total_by_offering = dict(
        Enrollment.objects.filter(
            class_group__offerings__id__in=offering_ids,
            status='active',
        ).values('class_group__offerings__id').annotate(
            cnt=Count('student', distinct=True)
        ).values_list('class_group__offerings__id', 'cnt')
    )

    graded_by_lesson = dict(
        Student.objects.filter(
            topicgrade__topic__lesson_id__in=lesson_ids
        ).values('topicgrade__topic__lesson_id').annotate(
            cnt=Count('id', distinct=True)
        ).values_list('topicgrade__topic__lesson_id', 'cnt')
    )

    result = {}
    for lesson in lessons:
        total = total_by_offering.get(lesson.offering_id, 0)
        graded = graded_by_lesson.get(lesson.id, 0)
        result[lesson.id] = int((graded / total) * 100) if total else 0
    return result


def recalculate_topic_weights(lesson):
    """Set all parent topics to equal weight summing to 100."""
    topics = list(Topic.objects.filter(lesson=lesson, parent__isnull=True))
    count = len(topics)
    if not count:
        return
    equal_share = round(100 / count, 2)
    for t in topics:
        t.weight = equal_share
        t.save(update_fields=['weight'])


def distribute_subtopic_weights(lesson):
    """Distribute subtopic weights equally under each parent topic."""
    parent_topics = Topic.objects.filter(lesson=lesson, parent__isnull=True)
    for topic in parent_topics:
        subtopics = list(Topic.objects.filter(parent=topic, lesson=lesson))
        if not subtopics:
            continue
        count = len(subtopics)
        equal_share = round(100 / count, 2)
        if count > 1:
            remainder = round(100 - equal_share * (count - 1), 2)
            for s in subtopics[:-1]:
                s.weight = equal_share
                s.save(update_fields=['weight'])
            subtopics[-1].weight = remainder
            subtopics[-1].save(update_fields=['weight'])
        else:
            subtopics[0].weight = 100.0
            subtopics[0].save(update_fields=['weight'])


def submit_grades(lesson, student, topics_data, subtopics_data, comment_mode='none'):
    """Process grade submission for a student on a lesson."""
    invalidate_lesson_grade_cache(lesson.id)
    to_merge = ''

    for topic in lesson.topics.filter(parent__isnull=True):
        topic_entry = topics_data.get(str(topic.id), {})
        subtopics = list(topic.subtopics.all())

        top_comment = topic_entry.get('comment', '').strip()
        top_comment_selected = topic_entry.get('comment_selected', False)

        if comment_mode == 'merged':
            to_merge += top_comment + ' \n\n'

        for sub in subtopics:
            sub_entry = subtopics_data.get(str(sub.id), {})
            covered = sub_entry.get('covered', False)
            sub_comment = sub_entry.get('comment', '').strip()
            sub_comment_selected = sub_entry.get('comment_selected', False)

            if comment_mode == 'merged':
                to_merge += sub_comment + '\n\n'

            TopicGrade.objects.update_or_create(
                student=student,
                topic=sub,
                defaults={
                    'grade': 100 if covered else 0,
                    'comment': sub_comment,
                    'comment_selected': sub_comment_selected,
                },
            )

        if subtopics:
            topic_grade_value = topic.calculate_subtopics_grade(student)
        else:
            covered = topic_entry.get('covered', False)
            topic_grade_value = 100 if covered else 0

        TopicGrade.objects.update_or_create(
            student=student,
            topic=topic,
            defaults={
                'grade': topic_grade_value,
                'comment': top_comment,
                'comment_selected': top_comment_selected,
            },
        )

    if comment_mode == 'merged':
        TopicGrade.objects.filter(
            topic__lesson=lesson,
            student=student,
        ).update(comment_selected=False)
        MergedLessonComment.objects.update_or_create(
            lesson=lesson,
            student=student,
            defaults={'comment_text': to_merge},
        )
    else:
        MergedLessonComment.objects.filter(
            lesson=lesson,
            student=student,
        ).delete()


def delete_student_grades(lesson, student, user=None):
    """Soft-delete all grades and delete merged comments for a student on a lesson."""
    from django.utils import timezone

    invalidate_lesson_grade_cache(lesson.id)
    now = timezone.now()
    TopicGrade.objects.filter(student=student, topic__lesson=lesson).update(
        is_deleted=True, deleted_at=now, deleted_by=user,
    )
    MergedLessonComment.objects.filter(lesson=lesson, student=student).delete()


def freeze_quarter_grades(offering_id, quarter, frozen_by_user):
    """Snapshot current grades for all enrolled students in an offering's quarter."""
    from apps.home.repo.students import grade_identifier

    offering = SubjectOffering.objects.select_related(
        'class_group', 'academic_year',
    ).get(id=offering_id)

    if QuarterGradeSnapshot.objects.filter(
        offering=offering, quarter=quarter, academic_year=offering.academic_year,
    ).exists():
        raise ValueError(f"Quarter {quarter} is already frozen for this offering.")

    enrollments = Enrollment.objects.filter(
        class_group=offering.class_group,
        academic_year=offering.academic_year,
        status='active',
    ).select_related('student')
    students = [e.student for e in enrollments]

    lessons = list(Lesson.objects.filter(offering=offering))
    quarter_lessons = [l for l in lessons if l.quarter == quarter]

    grades_map = Lesson.calculate_grades_bulk(quarter_lessons, students) if quarter_lessons else {}

    snapshots = []
    for student in students:
        grade_values = [grades_map.get((l.id, student.id), 0) for l in quarter_lessons]
        graded_count = sum(1 for g in grade_values if g > 0)
        avg = sum(grade_values) / len(grade_values) if grade_values else 0

        snapshots.append(QuarterGradeSnapshot(
            student=student,
            offering=offering,
            quarter=quarter,
            academic_year=offering.academic_year,
            final_grade=round(avg, 2),
            percentage=round(avg, 2),
            letter_grade=grade_identifier(avg) or '',
            lesson_count=len(quarter_lessons),
            graded_lesson_count=graded_count,
            frozen_by=frozen_by_user,
        ))

    QuarterGradeSnapshot.objects.bulk_create(snapshots)
    return len(snapshots)
