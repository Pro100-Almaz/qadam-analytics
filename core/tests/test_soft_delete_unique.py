"""Spec 0013, AC-5 — uniqueness counts live rows only.

For every live-only unique rule: soft-delete row A, create row C with the
same value, then try to restore A. The restore must be refused, name C, and
leave A deleted. `test_every_live_unique_constraint_has_a_case` keeps the
list complete.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.home.models import (
    AcademicYear, HomeroomTeacherAssignment, QuarterGrade, QuarterGrader,
)
from apps.lesson import homework_sync
from core.factories import (
    ClassGroupFactory, ClubAttendanceFactory, EnrollmentFactory,
    HomeworkFactory, HomeworkGradeFactory, ScheduleAttendanceFactory,
    ScheduleSessionFactory, SchoolFactory, StudentFactory,
    SubjectFactory, SubjectGradeFactory, SubjectOfferingFactory,
    SubjectScheduleFactory, TeacherFactory, TeachingAssignmentFactory,
    TopicFactory, TopicGradeFactory, UserFactory,
)
from core.soft_delete import _live_unique_constraints, soft_delete_models

pytestmark = pytest.mark.django_db


def _username():
    a = UserFactory(username='dup')
    return a, lambda: UserFactory(username='dup')


def _year_per_school():
    school = SchoolFactory()
    a = AcademicYear.objects.create(school=school, year='2040/2041')
    return a, lambda: AcademicYear.objects.create(school=school, year='2040/2041')


def _one_active_year():
    school = SchoolFactory()
    AcademicYear._base_manager.filter(school=school).update(is_active=False)
    a = AcademicYear.objects.create(school=school, year='2050/2051', is_active=True)
    return a, lambda: AcademicYear.objects.create(
        school=school, year='2051/2052', is_active=True,
    )


def _teaching_assignment():
    a = TeachingAssignmentFactory()
    return a, lambda: TeachingAssignmentFactory(offering=a.offering, teacher=a.teacher)


def _homeroom():
    class_group = ClassGroupFactory()
    a = HomeroomTeacherAssignment.objects.create(
        teacher=TeacherFactory(), class_group=class_group,
    )
    return a, lambda: HomeroomTeacherAssignment.objects.create(
        teacher=TeacherFactory(), class_group=class_group,
    )


def _enrollment():
    a = EnrollmentFactory()
    return a, lambda: EnrollmentFactory(student=a.student, class_group=a.class_group)


def _quarter_grader():
    subject = SubjectFactory()
    a = QuarterGrader.objects.create(subject=subject, quarter=2)
    return a, lambda: QuarterGrader.objects.create(subject=subject, quarter=2)


def _subject_assignment_detail():
    homework = HomeworkFactory()
    a = homework_sync.mirror_of(homework.pk)
    # The mirror alone, leaving the homework live: then the sync makes a new
    # mirror for the same detail_id, which is row C.
    a.delete(sync=False)
    return a, lambda: homework_sync.assignment_from_homework(homework)


def _subject_grade():
    a = SubjectGradeFactory()
    return a, lambda: SubjectGradeFactory(assignment=a.assignment, student=a.student)


def _quarter_grade():
    student, offering = StudentFactory(), SubjectOfferingFactory()
    a = QuarterGrade.objects.create(student=student, offering=offering, quarter=1, grade=4)
    return a, lambda: QuarterGrade.objects.create(
        student=student, offering=offering, quarter=1, grade=5,
    )


def _topic():
    parent = TopicFactory()
    a = TopicFactory(lesson=parent.lesson, parent=parent, title='Sub')
    return a, lambda: TopicFactory(lesson=parent.lesson, parent=parent, title='Sub')


def _topic_grade():
    a = TopicGradeFactory()
    return a, lambda: TopicGradeFactory(topic=a.topic, student=a.student)


def _subject_schedule():
    a = SubjectScheduleFactory(quarter=3)
    return a, lambda: SubjectScheduleFactory(offering=a.offering, quarter=3)


def _schedule_session():
    a = ScheduleSessionFactory()
    return a, lambda: ScheduleSessionFactory(schedule=a.schedule)


def _schedule_attendance():
    a = ScheduleAttendanceFactory(date=datetime.date(2026, 9, 7))
    return a, lambda: ScheduleAttendanceFactory(
        session=a.session, student=a.student, date=a.date,
    )


def _homework_grade():
    a = HomeworkGradeFactory(grade=3)
    # sync=False keeps the SubjectGrade mirror live, so C reuses it and the
    # only collision on restore is A against C itself.
    a.delete(sync=False)
    return a, lambda: HomeworkGradeFactory(homework=a.homework, student=a.student)


def _club_attendance():
    a = ClubAttendanceFactory(date=datetime.date(2026, 9, 7))
    return a, lambda: ClubAttendanceFactory(
        session=a.session, student=a.student, date=a.date,
    )


CASES = {
    'user_unique_live_username': _username,
    'academicyear_unique_year_per_school': _year_per_school,
    'academicyear_one_active_per_school': _one_active_year,
    'teachingassignment_unique_live_offering_teacher': _teaching_assignment,
    'homeroomassignment_unique_live_class_group': _homeroom,
    'unique_active_enrollment_per_class_group': _enrollment,
    'quartergrader_unique_live_subject_quarter': _quarter_grader,
    'subjectassignment_unique_detail': _subject_assignment_detail,
    'subjectgrade_unique_live_assignment_student': _subject_grade,
    'quartergrade_unique_live_student_offering_quarter': _quarter_grade,
    'topic_unique_live_lesson_parent_title': _topic,
    'topicgrade_unique_live_topic_student': _topic_grade,
    'subjectschedule_unique_live_offering_quarter': _subject_schedule,
    'schedulesession_unique_live_slot': _schedule_session,
    'scheduleattendance_one_per_slot': _schedule_attendance,
    'homeworkgrade_unique_live_homework_student': _homework_grade,
    'unique_active_club_attendance': _club_attendance,
}


def test_every_live_unique_constraint_has_a_case():
    names = {
        constraint.name
        for model in soft_delete_models()
        for constraint in _live_unique_constraints(model)
    }
    assert names == set(CASES)


@pytest.mark.parametrize('constraint', sorted(CASES))
def test_ac5_unique_value_reusable_after_delete(constraint):
    a, make_c = CASES[constraint]()
    if not a.is_deleted:
        a.delete()

    c = make_c()  # the deleted A does not block it

    with pytest.raises(ValidationError) as excinfo:
        a.restore()
    message = ' '.join(excinfo.value.messages)
    assert f'{type(c)._meta.verbose_name} #{c.pk}' in message
    assert type(a)._base_manager.get(pk=a.pk).is_deleted
