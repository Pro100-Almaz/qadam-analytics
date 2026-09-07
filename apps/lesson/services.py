from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.achievement.models import (
    Attachment, validate_attachment_format, validate_attachment_size,
)
from apps.authentication.models import Student, Teacher, Parent
from apps.home.models import SubjectOffering, Enrollment, TeachingAssignment
from apps.lesson.models import (
    Homework, Lesson, Topic, TopicGrade, MergedLessonComment,
    QuarterGradeSnapshot, SubjectSchedule,
)
from core.error_messages import OWN_OFFERINGS_ONLY
from core.permissions import is_admin_role, is_teacher_role

GRADE_CACHE_TTL = 300

# How many files one homework may carry. Keeps a single request bounded — the
# per-file size cap lives in apps.achievement.models.
MAX_HOMEWORK_ATTACHMENTS = 10


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


def get_comments_for_lesson_bulk(lessons: list[Lesson], students: list[Student]):
    if not lessons:
        return {}
    uncached_lessons = []
    cached_results = {}

    for lesson in lessons:
        key = f'grades:lesson:comments:{lesson.id}'
        cached = cache.get(key)
        if cached is not None:
            for student in students:
                comment = cached.get(student.id, {})
                cached_results[(lesson.id, student.id)] = comment
        else:
            uncached_lessons.append(lesson)

    if uncached_lessons:
        grades_map = Lesson.calculate_grades_bulk(uncached_lessons, students)
        fresh = Lesson.construct_comment_bulk(uncached_lessons, students, grades_map)
        cached_results.update(fresh)

        for lesson in uncached_lessons:
            lesson_comments = {
                s.id: fresh.get((lesson.id, s.id), {}) for s in students
            }
            cache.set(f'grades:lesson:comments:{lesson.id}', lesson_comments, GRADE_CACHE_TTL)
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
            class_group__subject_offerings__id__in=offering_ids,
            status='active',
        ).values('class_group__subject_offerings__id').annotate(
            cnt=Count('student', distinct=True)
        ).values_list('class_group__subject_offerings__id', 'cnt')
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
    to_merge = []

    for topic in lesson.topics.filter(parent__isnull=True):
        topic_entry = topics_data.get(str(topic.id), {})
        subtopics = list(topic.subtopics.all())

        top_comment = topic_entry.get('comment', '').strip()
        top_comment_selected = topic_entry.get('comment_selected', False)

        if (top_comment_selected or comment_mode == 'merged') and top_comment:
            to_merge.append(top_comment)

        for sub in subtopics:
            sub_entry = subtopics_data.get(str(sub.id), {})
            covered = sub_entry.get('covered', False)
            sub_comment = sub_entry.get('comment', '').strip()
            sub_comment_selected = sub_entry.get('comment_selected', False)

            if (sub_comment_selected or comment_mode == 'merged') and sub_comment:
                to_merge.append(sub_comment)

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

    MergedLessonComment.objects.update_or_create(
        lesson=lesson,
        student=student,
        defaults={'comment_text': '\n\n'.join(to_merge), 'is_merged': False},
    )
    if comment_mode == 'merged':
        TopicGrade.objects.filter(
            topic__lesson=lesson,
            student=student,
        ).update(comment_selected=False)
        MergedLessonComment.objects.filter(
            lesson=lesson,
            student=student
        ).update(is_merged=True)


def delete_student_grades(lesson, student, user=None):
    """Soft-delete all grades and delete merged comments for a student on a lesson."""
    from django.utils import timezone

    invalidate_lesson_grade_cache(lesson.id)
    TopicGrade.objects.filter(student=student, topic__lesson=lesson).delete()
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


def build_other_sessions_map(schedules):
    """
    Build {schedule_id: [ScheduleSession, ...]} of the rest of the class group's
    timetable.

    "Other" sessions are every session of the same class group and quarter that
    belongs to a different schedule — i.e. the slots taken by other subjects,
    which the client renders read-only next to the schedule's own sessions.

    Schedules without an offering (breaks, assemblies) carry a class group of
    their own, so they take part on exactly the same terms: they see the class
    group's subject slots and the subjects see them. The class group already
    pins the academic year, so the key needs only (class_group, quarter).
    """
    from apps.lesson.models import ScheduleSession

    schedules = list(schedules)
    if not schedules:
        return {}

    def key_for(schedule):
        return (schedule.class_group_id, schedule.quarter)

    wanted_keys = {key_for(s) for s in schedules}

    sessions = ScheduleSession.objects.filter(
        schedule__class_group_id__in={k[0] for k in wanted_keys},
        schedule__quarter__in={k[1] for k in wanted_keys},
    ).select_related(
        'schedule', 'schedule__offering', 'schedule__offering__subject',
    )

    sessions_by_key = {}
    for session in sessions:
        key = key_for(session.schedule)
        if key in wanted_keys:
            sessions_by_key.setdefault(key, []).append(session)

    result = {}
    for schedule in schedules:
        pool = sessions_by_key.get(key_for(schedule), [])
        result[schedule.id] = sorted(
            (s for s in pool if s.schedule_id != schedule.id),
            key=lambda s: (s.weekday, s.time_start, s.time_end),
        )
    return result


# ── Homework attachments ──
#
# Homework files live in the generic apps.achievement.Attachment table, reached
# through the Homework.attachments GenericRelation. Nothing here is specific to
# achievements — the model is simply the project's shared attachment store.

def homework_content_type():
    return ContentType.objects.get_for_model(Homework)


def validate_homework_attachments(files, existing_count=0):
    """
    Check an upload batch before anything is written.

    Size and format come from the shared attachment validators (10MB, PDFs and
    browser-safe images); the count cap is per homework, so an edit that adds
    files has to account for the ones already there.
    """
    if not files:
        return

    if existing_count + len(files) > MAX_HOMEWORK_ATTACHMENTS:
        raise serializers.ValidationError({
            'attachments': [
                f'A homework may have at most {MAX_HOMEWORK_ATTACHMENTS} '
                f'attachments ({existing_count} already attached).'
            ]
        })

    for uploaded_file in files:
        try:
            validate_attachment_size(uploaded_file)
            validate_attachment_format(uploaded_file)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                'attachments': [f'{uploaded_file.name}: {message}' for message in exc.messages]
            })


def attach_files_to_homeworks(homeworks, files, user):
    """
    Store every file on every homework — one Attachment row and one stored copy
    per homework.

    A single POST can create the same task for several classes at once; each
    class gets its own copy so that deleting one class's attachment (or the
    homework itself) never disturbs another's.
    """
    from apps.achievement.api.views import _detect_file_type

    if not homeworks or not files:
        return []

    content_type = homework_content_type()
    created = []
    with transaction.atomic():
        for homework in homeworks:
            for uploaded_file in files:
                # The same upload object is written once per homework; rewind it
                # so the second and later copies are not truncated.
                uploaded_file.seek(0)
                created.append(Attachment.objects.create(
                    content_type=content_type,
                    object_id=homework.pk,
                    file=uploaded_file,
                    file_type=_detect_file_type(uploaded_file.name),
                    original_name=uploaded_file.name,
                    uploaded_by=user,
                ))
    return created


def homework_attachments(homework):
    """Attachments of one homework, oldest first."""
    return homework.attachments.order_by('created_at', 'id')


def delete_homework_attachments(homework, attachment_ids):
    """
    Remove the given attachments from a homework, file and row.

    Ids that do not belong to this homework are rejected rather than ignored —
    a typo in the payload should not pass silently as a successful edit.
    """
    if not attachment_ids:
        return 0

    ids = set(attachment_ids)
    rows = list(homework.attachments.filter(pk__in=ids))
    missing = ids - {row.pk for row in rows}
    if missing:
        raise serializers.ValidationError({
            'remove_attachments': [
                'These attachments do not belong to this homework: '
                + ', '.join(str(pk) for pk in sorted(missing))
            ]
        })

    with transaction.atomic():
        for row in rows:
            row.file.delete(save=False)
            row.delete()
    return len(rows)
