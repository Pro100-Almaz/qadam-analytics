"""One live row of every soft-deletable model (spec 0014).

`BUILDERS` is keyed by model label and must cover `soft_delete_models()`
exactly — `test_registry_has_a_builder_for_every_model` fails when a model
gains the mixin without a builder here, so AC-1 can never silently skip one.
"""

import datetime

from apps.achievement.models import Achievement, ClubEntry, ReadingEntry
from apps.authentication.models import PsychologicalState
from apps.home.models import (
    ClassGroupCollection, HomeroomTeacherAssignment, QuarterGrade, QuarterGrader,
)
from apps.lesson.models import MergedLessonComment
from apps.notification.models import Notification
from apps.student_report.models import StudentReport
from core.factories import (
    AcademicYearFactory, ClassGroupFactory, ClubAttendanceFactory,
    ClubFactory, ClubManagerFactory, ClubSessionFactory, EnrollmentFactory,
    HomeworkFactory, HomeworkGradeFactory, LessonFactory, ParentFactory,
    ScheduleAttendanceFactory, ScheduleSessionFactory, StudentFactory,
    SubjectAssignmentFactory, SubjectFactory, SubjectGradeFactory,
    SubjectOfferingFactory, SubjectScheduleFactory, SupervisorFactory,
    TeacherFactory, TeachingAssignmentFactory, TopicFactory,
    TopicGradeFactory, UserFactory,
)


def _year():
    return AcademicYearFactory(is_active=False)


BUILDERS = {
    'authentication.CustomUser': lambda: UserFactory(),
    'authentication.Student': lambda: StudentFactory(),
    'authentication.Teacher': lambda: TeacherFactory(),
    'authentication.Parent': lambda: ParentFactory(),
    'authentication.Supervisor': lambda: SupervisorFactory(),
    'authentication.ClubManager': lambda: ClubManagerFactory(),
    'authentication.PsychologicalState': lambda: PsychologicalState.objects.create(
        name='Calm', student=StudentFactory(),
    ),
    'home.AcademicYear': _year,
    'home.ClassGroup': lambda: ClassGroupFactory(),
    'home.ClassGroupCollection': lambda: ClassGroupCollection.objects.create(
        major=ClassGroupFactory(),
    ),
    'home.Subject': lambda: SubjectFactory(),
    'home.SubjectOffering': lambda: SubjectOfferingFactory(),
    'home.TeachingAssignment': lambda: TeachingAssignmentFactory(),
    'home.HomeroomTeacherAssignment': lambda: HomeroomTeacherAssignment.objects.create(
        teacher=TeacherFactory(), class_group=ClassGroupFactory(),
    ),
    'home.Enrollment': lambda: EnrollmentFactory(),
    'home.QuarterGrader': lambda: QuarterGrader.objects.create(
        subject=SubjectFactory(), quarter=1,
    ),
    'home.SubjectAssignment': lambda: SubjectAssignmentFactory(),
    'home.SubjectGrade': lambda: SubjectGradeFactory(),
    'home.QuarterGrade': lambda: QuarterGrade.objects.create(
        student=StudentFactory(), offering=SubjectOfferingFactory(),
        quarter=1, grade=4,
    ),
    'lesson.Lesson': lambda: LessonFactory(),
    'lesson.Topic': lambda: TopicFactory(),
    'lesson.TopicGrade': lambda: TopicGradeFactory(),
    'lesson.MergedLessonComment': lambda: MergedLessonComment.objects.create(
        lesson=LessonFactory(), comment_text='Well done',
    ),
    'lesson.SubjectSchedule': lambda: SubjectScheduleFactory(),
    'lesson.ScheduleSession': lambda: ScheduleSessionFactory(),
    'lesson.ScheduleAttendance': lambda: ScheduleAttendanceFactory(),
    'lesson.Homework': lambda: HomeworkFactory(),
    'lesson.HomeworkGrade': lambda: HomeworkGradeFactory(),
    'student_report.StudentReport': lambda: StudentReport.objects.create(
        student=StudentFactory(), academic_year=_year(), quarter=1,
    ),
    'notification.Notification': lambda: Notification.objects.create(
        user=UserFactory(), type=Notification.NotificationType.LOGIN,
    ),
    'achievement.Achievement': lambda: Achievement.objects.create(
        student=StudentFactory(), academic_year=_year(), category='project',
    ),
    'achievement.ReadingEntry': lambda: ReadingEntry.objects.create(
        student=StudentFactory(), academic_year=_year(), title='Abai', month=1,
    ),
    'achievement.ClubEntry': lambda: ClubEntry.objects.create(
        student=StudentFactory(), academic_year=_year(), month=1, club_name='Chess',
    ),
    'achievement.Club': lambda: ClubFactory(),
    'achievement.ClubSession': lambda: ClubSessionFactory(),
    'achievement.ClubAttendance': lambda: ClubAttendanceFactory(
        date=datetime.date(2026, 9, 7),
    ),
}
