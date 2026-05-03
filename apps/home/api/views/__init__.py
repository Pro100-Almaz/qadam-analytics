from .dashboard import DashboardStatsAPIView
from .academic import AcademicYearListAPIView, ClassGroupListAPIView
from .students import (
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
from .teachers import (
    TeacherListAPIView,
    TeacherDetailAPIView,
    TeacherProfileUpdateAPIView,
    ParentTeacherListAPIView,
)
from .subjects import (
    SubjectListAPIView,
    SubjectCreateAPIView,
    SubjectDetailAPIView,
    SubjectGradesAPIView,
    SubjectStatusAPIView,
    SubjectDeleteAPIView,
    MySubjectsListAPIView,
)
from .enrollments import EnrollmentListAPIView
from .parents import (
    ParentChildrenListAPIView,
    ParentChildDetailAPIView,
    ParentTeachersAPIView,
)

__all__ = [
    'DashboardStatsAPIView',
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
    'EnrollmentListAPIView',
    'ParentChildrenListAPIView',
    'ParentChildDetailAPIView',
    'ParentTeachersAPIView',
]
