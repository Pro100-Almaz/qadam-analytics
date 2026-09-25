---
id: 0002
slug: teacher-interface
title: Teacher Interface — role-aware frontend
status: in-progress
owner: almaz
created: 2026-05-27
updated: 2026-09-21
---

> **Migrated document.** Predates the spec workflow; content below is unchanged.
> It is an interface contract rather than a full spec — it lacks explicit
> acceptance criteria. Add them before treating it as approved.

# Teacher Interface — Frontend Implementation Spec

## Overview

The teacher interface is role-aware. A single user may hold multiple teacher roles simultaneously (e.g., a lesson teacher who is also a homeroom teacher). The frontend should detect the user's roles from the unified dashboard endpoint and render the appropriate tabs/sections.

### Three Teacher Subtypes

| Subtype | Django Group | Responsibility |
|---------|-------------|----------------|
| **Lesson Teacher** | `Teacher` | Teaches specific subjects to specific classes. Manages lessons, topics, grading. |
| **Homeroom Teacher** | `HomeroomTeacher` | Assigned to a class group. Monitors all students' academic performance and well-being across all subjects. |
| **Psychologist** | `Psychologist` | Monitors psychological/emotional states of students school-wide. |

---

## Authentication

All endpoints require JWT authentication:
```
Authorization: Bearer <access_token>
```

Tokens obtained via `POST /api/v1/auth/login/` (30min access, 7-day refresh).

---

## Endpoints

### 1. Unified Teacher Dashboard

**`GET /api/v1/teacher/dashboard/`**

Permission: Any teacher subtype or admin.

Returns role-appropriate dashboard data based on the authenticated user's groups. Use this as the single entry point to determine which UI sections to render.

**Response:**
```json
{
    "user_id": 42,
    "full_name": "Almaz Amanzholuly",
    "roles": ["Teacher", "HomeroomTeacher"],
    "dashboards": {
        "lesson_teacher": { ... },
        "homeroom_teacher": { ... },
        "psychologist": { ... }
    }
}
```

Only the keys matching the user's roles will be present in `dashboards`.

#### `dashboards.lesson_teacher`

```json
{
    "offerings": [
        {
            "offering_id": 1,
            "subject_name": "Mathematics",
            "class_group": "7A",
            "role": "primary",
            "lesson_count": 24,
            "student_count": 28,
            "graded_lessons": 20,
            "grading_percentage": 83.3
        }
    ],
    "summary": {
        "total_offerings": 4,
        "total_lessons": 96,
        "total_graded": 80,
        "total_ungraded": 16,
        "grading_percentage": 83.3
    }
}
```

#### `dashboards.homeroom_teacher`

```json
{
    "class_group": "7A",
    "class_group_id": 12,
    "student_count": 28,
    "subject_count": 8,
    "students": [
        {
            "student_id": 101,
            "user_id": 201,
            "full_name": "Student Name",
            "overall_average": 78.5,
            "overall_letter": "B",
            "subjects": [
                {
                    "subject_name": "Mathematics",
                    "average": 85.2,
                    "letter_grade": "A"
                },
                {
                    "subject_name": "Physics",
                    "average": null,
                    "letter_grade": null
                }
            ],
            "psychological_state": {
                "name": "Anxious",
                "score": 2,
                "date": "2026-04-28T10:30:00+06:00"
            }
        }
    ]
}
```

#### `dashboards.psychologist`

```json
{
    "stats": {
        "total_records": 342,
        "average_score": 3.4,
        "records_last_30_days": 45,
        "score_distribution": {
            "1": 12,
            "2": 34,
            "3": 120,
            "4": 98,
            "5": 78
        }
    },
    "recent_states": [
        {
            "id": 456,
            "student_id": 101,
            "student_name": "Student Name",
            "name": "Anxious",
            "score": 2,
            "comment": "Shows signs of test anxiety",
            "added_by": "Teacher Name",
            "time_added": "2026-05-03T14:20:00+06:00"
        }
    ],
    "students_needing_attention": [
        {
            "student_id": 101,
            "full_name": "Student Name",
            "low_score_count": 5,
            "average_score": 1.8
        }
    ]
}
```

---

### 2. Homeroom Class Detail

**`GET /api/v1/teacher/my-class/`**

Permission: `HomeroomTeacher` or admin.

Same response shape as `dashboards.homeroom_teacher` above. Use when you need to fetch the homeroom data independently (e.g., on a dedicated "My Class" page).

**Error responses:**
- `404` — No teacher profile or no homeroom class assigned for current year.

---

### 3. My Classes (Class List)

**`GET /api/v1/teacher/my-classes/`**

Permission: Any teacher subtype or admin.

Returns all class groups the teacher is associated with — either through subject offerings (lesson teacher) or homeroom assignment. This is the first screen: teacher sees their classes, then clicks to drill into students.

**Response:**
```json
[
    {
        "class_group_id": 12,
        "display_name": "7A",
        "grade_level": 7,
        "letter": "A",
        "student_count": 28,
        "subjects": [
            {
                "offering_id": 1,
                "subject_name": "Mathematics",
                "role": "primary"
            }
        ],
        "is_homeroom": true
    },
    {
        "class_group_id": 15,
        "display_name": "8B",
        "grade_level": 8,
        "letter": "B",
        "student_count": 25,
        "subjects": [
            {
                "offering_id": 5,
                "subject_name": "Mathematics",
                "role": "primary"
            }
        ],
        "is_homeroom": false
    }
]
```

**UI Notes:**
- Show each class as a card with class name, student count, and subject chips
- If `is_homeroom: true`, show a badge/indicator
- Clicking a class navigates to the students list

---

### 4. Class Students (Drill-Down)

**`GET /api/v1/teacher/my-classes/<class_group_id>/students/`**

Permission: Any teacher subtype or admin.

Query params:
- `all_subjects=true` — show grades for ALL subjects in that class (default: only the teacher's own subjects)

Returns the student list for a class, with per-subject grades. For a **lesson teacher**, only their taught subjects are shown by default. For a **homeroom teacher** or with `all_subjects=true`, all subjects are shown.

**Response:**
```json
{
    "class_group_id": 12,
    "class_group": "7A",
    "student_count": 28,
    "subject_count": 3,
    "students": [
        {
            "student_id": 101,
            "user_id": 201,
            "full_name": "Student Name",
            "avatar": "/media/avatars/2026/05/04/photo.jpg",
            "overall_average": 78.5,
            "overall_letter": "B",
            "subjects": [
                {
                    "offering_id": 1,
                    "subject_name": "Mathematics",
                    "average": 85.2,
                    "letter_grade": "A",
                    "lesson_count": 24
                },
                {
                    "offering_id": 2,
                    "subject_name": "Physics",
                    "average": null,
                    "letter_grade": null,
                    "lesson_count": 0
                }
            ],
            "psychological_state": {
                "name": "Calm",
                "score": 4
            }
        }
    ]
}
```

**UI Notes:**
- Render as a table: Name | Subject1 | Subject2 | ... | Overall | Psych State
- Subject columns use color-coded cells based on letter grade
- Psych state shown as a colored badge (1-2 red, 3 amber, 4-5 green)
- Clicking a student row navigates to their detail page (`/api/v1/students/<id>/`)
- Homeroom teachers see a toggle/button to switch between "My subjects" and "All subjects"

---

### 5. Psychologist Dashboard

**`GET /api/v1/teacher/psychologist/`**

Permission: `Psychologist` or admin.

Same response shape as `dashboards.psychologist` above. Use for the dedicated psychologist page.

---

### 6. Psychologist — Student Detail

**`GET /api/v1/teacher/psychologist/students/<student_id>/`**

Permission: `Psychologist` or admin.

Returns full psychological state history for a specific student.

**Response:**
```json
{
    "student_id": 101,
    "full_name": "Student Name",
    "total_records": 12,
    "average_score": 3.2,
    "history": [
        {
            "id": 456,
            "name": "Anxious",
            "score": 2,
            "comment": "Shows signs of test anxiety",
            "added_by": "Teacher Name",
            "time_added": "2026-05-03T14:20:00+06:00"
        }
    ]
}
```

---

### 7. Teacher Workload (existing)

**`GET /api/v1/dashboard/teacher-workload/`**

Permission: Any teacher or admin.

Query params:
- `teacher_id` (optional) — admin can view any teacher's workload
- `week_start` (optional, `YYYY-MM-DD`) — defaults to current week Monday
- `week_end` (optional, `YYYY-MM-DD`) — defaults to current week Sunday

**Response:**
```json
{
    "teacher_id": 42,
    "period": "2026-05-04 to 2026-05-10",
    "lessons_taught": 12,
    "lessons_upcoming": 8,
    "lessons_without_topics": 3,
    "grading_completion": {
        "total_lessons_to_grade": 12,
        "fully_graded": 9,
        "partially_graded": 2,
        "ungraded": 1,
        "completion_percentage": 75.0
    },
    "subjects": [
        {
            "subject_name": "Mathematics",
            "class_group": "5A",
            "lessons_this_week": 3,
            "grading_complete": true
        }
    ]
}
```

---

### 8. Existing Endpoints Used by Teachers

These endpoints are already implemented and should be linked from teacher dashboard cards:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/lessons/` | GET | List lessons (filter: `class_group`, `subject`, `quarter`) |
| `/api/v1/lessons/` | POST | Create lesson |
| `/api/v1/lessons/<id>/` | GET | Lesson detail with topics and grades |
| `/api/v1/lessons/<lesson_id>/grading/` | GET | Grading page data |
| `/api/v1/lessons/<lesson_id>/grading/` | POST | Submit grades |
| `/api/v1/lessons/<lesson_id>/grading/` | PATCH | Update grades |
| `/api/v1/calendar/lessons/` | GET | Calendar view of lessons |
| `/api/v1/students/<pk>/` | GET | Student detail |
| `/api/v1/students/<pk>/psychological-state/` | POST | Add psychological state |
| `/api/v1/psychological-states/<pk>/` | DELETE | Delete psychological state |
| `/api/v1/psychological-state-templates/` | GET | List state templates |

---

## Frontend Architecture

### Routing

```
/teacher/                        → TeacherDashboard (auto-detect role, summary cards)
/teacher/my-classes/             → Class list (cards for each class group)
/teacher/my-classes/:classId     → Students table for that class (drill-down)
/teacher/my-classes/:classId/:studentId → Student detail
/teacher/offerings/:id/lessons   → Lessons for an offering
/teacher/my-class/               → Homeroom: class overview with cross-subject grades
/teacher/psychologist/           → Psychologist dashboard
/teacher/psychologist/:studentId → Student psych history detail
/teacher/workload/               → Weekly workload view
```

### Role Detection & Tab Rendering

On page load, call `GET /api/v1/teacher/dashboard/` once. The `roles` array and `dashboards` keys determine which tabs/navigation items to show:

```javascript
const { roles, dashboards } = await fetchTeacherDashboard();

const tabs = [];
if (dashboards.lesson_teacher) tabs.push({ key: 'lessons', label: 'My Subjects' });
if (dashboards.homeroom_teacher) tabs.push({ key: 'my-class', label: 'My Class' });
if (dashboards.psychologist) tabs.push({ key: 'psychologist', label: 'Psychological States' });
```

### Component Structure

```
TeacherLayout/
  TabNavigation (based on roles)
  
  LessonTeacherDashboard/
    OfferingSummaryCards          → summary stats
    OfferingsList                → table of offerings with grading %
      OfferingRow                → click to navigate to lessons
    GradingProgressBar           → total grading completion
  
  HomeroomDashboard/
    ClassHeader                  → class name, student/subject count
    StudentsGradeTable           → sortable table with all subjects as columns
      StudentRow                 → name | Math | Physics | ... | Overall | Psych State
        SubjectGradeCell         → colored by letter grade
        PsychStateBadge          → score as colored badge (1-2 red, 3 yellow, 4-5 green)
    StudentDetailModal           → expanded view on row click
  
  PsychologistDashboard/
    StatsCards                   → total records, avg score, last 30 days
    ScoreDistributionChart       → bar chart of 1-5 distribution
    AttentionList                → students with low scores, sorted by frequency
      AttentionRow               → click to open student detail
    RecentStatesList             → latest 20 states across all students
    
  PsychologistStudentDetail/
    StudentHeader                → name, total records, avg score
    ScoreTrendChart              → line chart of scores over time
    StateHistory                 → chronological list of all states
    AddStateButton               → opens form (POST to existing endpoint)
```

### Color Coding

**Letter grades:**
| Grade | Color | Range |
|-------|-------|-------|
| A | `#4CAF50` (green) | 90-100 |
| B | `#8BC34A` (light green) | 75-89 |
| C | `#FFC107` (amber) | 60-74 |
| D | `#FF9800` (orange) | 40-59 |
| F | `#F44336` (red) | 0-39 |

**Psychological state scores:**
| Score | Color | Meaning |
|-------|-------|---------|
| 1-2 | `#F44336` (red) | Needs attention |
| 3 | `#FFC107` (amber) | Neutral |
| 4-5 | `#4CAF50` (green) | Good |

### Data Fetching Strategy

1. **Initial load**: Single call to `/api/v1/teacher/dashboard/` provides all data for the landing page.
2. **Tab navigation**: Each tab can use the data already fetched from the dashboard response. Only fetch additional data when the user drills deeper:
   - Clicking an offering row → `GET /api/v1/lessons/?offering=<id>&quarter=<q>`
   - Clicking a student in homeroom → `GET /api/v1/students/<id>/`
   - Clicking a student in psychologist view → `GET /api/v1/teacher/psychologist/students/<id>/`
3. **Refresh**: Re-fetch dashboard data when user switches back to dashboard tab or after grading actions.

### Permissions in UI

- **Lesson Teacher** can: view/create/grade lessons for their own offerings
- **Homeroom Teacher** can: view all students' grades in their class, add psychological states
- **Psychologist** can: view all psychological states, add new states to any student, see attention alerts
- **Admin** sees: all dashboards combined

Hide UI elements that the user's role doesn't permit. The API will also enforce permissions server-side.

---

## Database Migrations Required

Before frontend development, ensure backend has run:

```bash
python manage.py makemigrations
python manage.py migrate
```

New migrations will be created for:
- `HomeroomTeacherAssignment` model (home app)
- `is_deleted`, `deleted_at`, `deleted_by` fields on Lesson, Topic, TopicGrade, Achievement, ReadingEntry, ClubEntry
- `HistoricalRecords` tables for Lesson, Topic, TopicGrade, Enrollment, Student
- `QuarterGradeSnapshot` model

Also create the `Psychologist` group in Django admin or via:
```python
from django.contrib.auth.models import Group
Group.objects.get_or_create(name='Psychologist')
```

And assign homeroom teachers to classes via Django admin or a management command by creating `HomeroomTeacherAssignment` records.

---

## API Base URL

All endpoints are prefixed with `/api/v1/`. The base URL depends on the environment:

| Environment | Base URL |
|-------------|----------|
| Local dev | `http://localhost:8000/api/v1/` |
| Production | `https://qadam.kz/api/v1/` |
