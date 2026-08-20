from apps.home.api.views.dashboard import DashboardStatsAPIView, TeacherWorkloadAPIView
from apps.home.api.views.academic import AcademicYearListAPIView, ClassGroupListAPIView, RolloverAcademicYearAPIView
from apps.home.api.views.students import (
    StudentListAPIView,
    StudentDetailAPIView,
    StudentProfileUpdateAPIView,
    PsychologicalStateCreateAPIView,
    PsychologicalStateDeleteAPIView,
    PsychologicalStateTemplateListAPIView,
    StudentMySubjectsAPIView,
    StudentMyTeachersAPIView,
    StudentClassmatesAPIView,
)
from apps.home.api.views.teachers import (
    TeacherListAPIView,
    TeacherDetailAPIView,
    TeacherProfileUpdateAPIView,
    ParentTeacherListAPIView,
)
from apps.home.api.views.subjects import (
    SubjectListAPIView,
    SubjectCreateAPIView,
    SubjectDetailAPIView,
    SubjectGradesAPIView,
    SubjectStatusAPIView,
    SubjectDeleteAPIView,
    MySubjectsListAPIView,
)
from apps.home.api.views.enrollments import EnrollmentListAPIView
from apps.home.api.views.parents import (
    ParentChildrenListAPIView,
    ParentChildDetailAPIView,
    ParentTeachersAPIView,
    ParentChildSubjectDetailAPIView,
)
from apps.home.api.views.assignments import (
    SubjectAssignmentListCreateAPIView,
    SubjectAssignmentDetailAPIView,
    SubjectAssignmentGradeListCreateAPIView,
    SubjectGradeListAPIView,
    SubjectGradeDetailAPIView,
    HomeroomSubjectGradeListAPIView,
)
from apps.home.api.views.quarter_grades import (
    QuarterGradeListCreateAPIView,
    QuarterGradeDetailAPIView,
    HomeroomQuarterGradeListAPIView,
)
from apps.home.api.views.teacher_dashboard import (
    TeacherRoleDashboardAPIView,
    HomeroomClassAPIView,
    PsychologistDashboardAPIView,
    PsychologistStudentDetailAPIView,
    TeacherMyClassesAPIView,
    TeacherClassStudentsAPIView,
)

__all__ = [
    'DashboardStatsAPIView',
    'TeacherWorkloadAPIView',
    'AcademicYearListAPIView',
    'ClassGroupListAPIView',
    'StudentListAPIView',
    'StudentDetailAPIView',
    'StudentProfileUpdateAPIView',
    'PsychologicalStateCreateAPIView',
    'PsychologicalStateDeleteAPIView',
    'PsychologicalStateTemplateListAPIView',
    'StudentMySubjectsAPIView',
    'StudentMyTeachersAPIView',
    'StudentClassmatesAPIView',
    'TeacherListAPIView',
    'TeacherDetailAPIView',
    'TeacherProfileUpdateAPIView',
    'ParentTeacherListAPIView',
    'SubjectListAPIView',
    'SubjectCreateAPIView',
    'SubjectDetailAPIView',
    'SubjectGradesAPIView',
    'SubjectStatusAPIView',
    'SubjectDeleteAPIView',
    'MySubjectsListAPIView',
    'RolloverAcademicYearAPIView',
    'EnrollmentListAPIView',
    'ParentChildrenListAPIView',
    'ParentChildDetailAPIView',
    'ParentTeachersAPIView',
    'TeacherRoleDashboardAPIView',
    'HomeroomClassAPIView',
    'PsychologistDashboardAPIView',
    'PsychologistStudentDetailAPIView',
    'TeacherMyClassesAPIView',
    'TeacherClassStudentsAPIView',
    'SubjectAssignmentListCreateAPIView',
    'SubjectAssignmentDetailAPIView',
    'SubjectAssignmentGradeListCreateAPIView',
    'SubjectGradeListAPIView',
    'SubjectGradeDetailAPIView',
    'HomeroomSubjectGradeListAPIView',
    'QuarterGradeListCreateAPIView',
    'QuarterGradeDetailAPIView',
    'HomeroomQuarterGradeListAPIView',
]
