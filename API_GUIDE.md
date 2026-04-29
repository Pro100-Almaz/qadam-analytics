# Qadam Analytics API — Frontend Integration Guide

**Base URL:** `http://localhost:8000/api/v1/`
**Swagger UI:** `http://localhost:8000/api/docs/`
**API Schema:** `http://localhost:8000/api/schema/`

---

## Authentication

All endpoints (except login, password reset, and school groups) require a JWT access token.

### Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

### Token Lifecycle

- **Access token** expires in 30 minutes
- **Refresh token** expires in 7 days (rotation enabled — each refresh returns a new pair)
- On 401 response, call the refresh endpoint. If that also fails, redirect to login.

---

## 1. Auth Endpoints

### POST `/auth/login/`

Login and receive JWT tokens.

**Request:**
```json
{
  "username": "admin@school.kz",
  "password": "secret123"
}
```

**Response (200):**
```json
{
  "tokens": {
    "access": "eyJ...",
    "refresh": "eyJ..."
  },
  "user": {
    "id": 1,
    "username": "admin@school.kz",
    "email": "admin@school.kz",
    "first_name": "Almaz",
    "last_name": "Amanzholuly",
    "phone_number": "+77001234567",
    "date_of_birth": "1990-01-15",
    "address": "Almaty",
    "avatar": "/media/avatars/photo.jpg",
    "school": "nisa",
    "role": "admin",
    "role_display": "Admin",
    "primary_group": "Admin"
  }
}
```

**Errors:**
- `400` — `{"username": ["Логин не совпадает"]}` or `{"password": ["Пароль не совпадает"]}`

---

### POST `/auth/token/refresh/`

Refresh an expired access token.

**Request:**
```json
{
  "refresh": "eyJ..."
}
```

**Response (200):**
```json
{
  "access": "eyJ...",
  "refresh": "eyJ..."
}
```

> Store the new refresh token — the old one is blacklisted after use.

---

### POST `/auth/logout/`

Blacklist the refresh token. Requires auth.

**Request:**
```json
{
  "refresh": "eyJ..."
}
```

**Response:** `204 No Content`

---

### POST `/auth/register/`

Create a new user. **Admin-only** — requires authenticated admin token.

**Headers:** `Content-Type: multipart/form-data` (supports avatar upload)

**Request fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `first_name` | string | yes | |
| `last_name` | string | yes | |
| `email` | string | yes | Used as username |
| `password1` | string | yes | |
| `password2` | string | yes | Must match password1 |
| `role` | string | yes | One of: `Admin`, `Teacher`, `HomeroomTeacher`, `Student`, `Supervisor`, `Principal`, `Parent` |
| `school` | string | no | School choice |
| `phone_number` | string | no | |
| `date_of_birth` | date | no | `YYYY-MM-DD` |
| `address` | string | no | |
| `avatar` | file | no | Image file |
| `gender` | string | no | Teacher only: `M` or `F` |
| `academic_degree` | string | no | Teacher only |
| `employment_type` | string | no | Teacher only |
| `occupation` | string | no | Teacher only |
| `school_group` | integer | no | Student only: SchoolGroup ID |
| `student_id` | integer | no | Parent only: link to existing Student |

**Response (201):**
```json
{
  "user": { /* UserSerializer fields */ }
}
```

---

### GET `/auth/me/`

Get current user profile. Requires auth.

**Response (200):**
```json
{
  "id": 1,
  "username": "admin@school.kz",
  "email": "admin@school.kz",
  "first_name": "Almaz",
  "last_name": "Amanzholuly",
  "phone_number": "+77001234567",
  "date_of_birth": "1990-01-15",
  "address": "Almaty",
  "avatar": "/media/avatars/photo.jpg",
  "school": "nisa",
  "role": "admin",
  "role_display": "Admin",
  "primary_group": "Admin"
}
```

### PATCH `/auth/me/`

Update current user profile. Requires auth.

**Request (partial update):**
```json
{
  "first_name": "New Name",
  "phone_number": "+77009876543"
}
```

**Editable fields:** `email`, `first_name`, `last_name`, `phone_number`, `date_of_birth`, `address`

---

### POST `/auth/me/avatar/`

Upload avatar. `Content-Type: multipart/form-data`. Requires auth.

**Request:** form field `avatar` with image file.

**Response (200):**
```json
{
  "avatar": "/media/avatars/new_photo.jpg"
}
```

---

### Password Reset Flow

**Step 1 — POST `/auth/forget-password/`** (no auth)

```json
{ "username": "user@school.kz" }
```
Response: `{ "username": "user@school.kz", "signed_code": "abc123..." }`

**Step 2 — POST `/auth/verify-code/<username>/<signed_code>/`** (no auth)

```json
{ "verification_code": "1234" }
```
Response: `{ "username": "...", "signed_code": "...", "verified": true }`

**Step 3 — POST `/auth/change-password/<username>/<signed_code>/`** (no auth)

```json
{ "password1": "newpass", "password2": "newpass" }
```
Response: `{ "detail": "Пароль успешно изменен!" }`

### Alternative: Link-based Reset

**POST `/auth/reset/<uidb64>/<token>/`** (no auth)

```json
{ "new_password": "newpass", "confirm_password": "newpass" }
```

---

### GET `/auth/school-groups/`

List all school groups. No auth required.

**Response (200):**
```json
[
  { "id": 1, "name": "NIS Almaty", "avatar": "/media/school_groups/logo.png" },
  { "id": 2, "name": "NIS Astana", "avatar": null }
]
```

---

## 2. Dashboard

### GET `/dashboard/stats/`

Requires auth.

**Response (200):**
```json
{
  "total_students": 450,
  "total_teachers": 35,
  "total_classes": 18
}
```

---

## 3. Academic Structure

### GET `/academic-years/`

**Response (200):**
```json
[
  { "id": 1, "year": "2025-2026", "is_active": true, "archived": false },
  { "id": 2, "year": "2024-2025", "is_active": false, "archived": true }
]
```

### GET `/class-groups/?year=1`

**Query params:** `year` (optional) — filter by academic year ID.

**Response (200):**
```json
[
  {
    "id": 1,
    "letter": "A",
    "grade_level": { "id": 1, "number": 7 },
    "academic_year": { "id": 1, "year": "2025-2026", "is_active": true, "archived": false },
    "display_name": "7A"
  }
]
```

---

## 4. Students

**Roles:** Admin, Supervisor, Principal, Teacher, HomeroomTeacher can list/view students.

### GET `/students/?year=1&class_group=3`

List students. Paginated (default page size 20, currently disabled).

**Query params:**
- `year` — academic year ID (defaults to latest)
- `class_group` — filter by class group ID

**Response (200):**
```json
[
  {
    "id": 5,
    "user": { /* UserSerializer */ },
    "school_group": 1,
    "academic_year": 1,
    "current_class_group": {
      "id": 3,
      "letter": "B",
      "grade_level": { "id": 2, "number": 8 },
      "academic_year": { /* ... */ },
      "display_name": "8B"
    }
  }
]
```

### GET `/students/<user_id>/`

Student detail by **CustomUser.id** (not Student.id).

Returns full profile including grades, psychological states.

**Response (200):**
```json
{
  "id": 5,
  "user": { /* UserSerializer */ },
  "school_group": 1,
  "academic_year": 1,
  "current_class_group": { /* ClassGroupSerializer */ },
  "offerings": [ /* SubjectOfferingSerializer[] */ ],
  "subject_quarter_grades": {
    "1": { "Math": 85.3, "Physics": 72.1 },
    "2": { "Math": 88.0, "Physics": 75.5 },
    "3": {},
    "4": {}
  },
  "total_quarter_grades": {
    "1": 5,
    "2": 4,
    "3": 2,
    "4": 2
  },
  "cumulative_subject_grades": {
    "Math": 43.3,
    "Physics": 36.9
  },
  "student_total_grade": 3.2,
  "psychological_states": {
    "current": [
      {
        "id": 10,
        "name": "Anxiety",
        "score": 3,
        "comment": "Moderate levels",
        "added_by": "Dr. Smith",
        "time_added": "2026-04-20T10:30:00+05:00"
      }
    ],
    "history": {
      "Anxiety": [
        { "id": 8, "name": "Anxiety", "score": 4, "comment": "...", "added_by": "...", "time_added": "..." },
        { "id": 10, "name": "Anxiety", "score": 3, "comment": "...", "added_by": "...", "time_added": "..." }
      ]
    }
  }
}
```

### PATCH `/students/<student_id>/update/`

Update student profile. **Admin-only.** Uses `Student.pk` (not user ID).

**Request:**
```json
{
  "first_name": "Updated Name",
  "email": "new@email.kz",
  "school_group": 2,
  "academic_year": 1,
  "class_group": 5
}
```

**Editable fields:** `email`, `first_name`, `last_name`, `phone_number`, `date_of_birth`, `address`, `school_group` (ID), `academic_year` (ID), `class_group` (ID — triggers enrollment)

---

### POST `/students/<student_pk>/psychological-state/`

Create psychological state for a student. Teacher/Admin/Supervisor only.

**Request:**
```json
{
  "state_name": "Anxiety",
  "score": 3,
  "comment": "Moderate levels observed"
}
```

**Response (201):**
```json
{
  "id": 15,
  "name": "Anxiety",
  "score": 3,
  "comment": "Moderate levels observed",
  "time_added": "2026-04-28T16:00:00+05:00"
}
```

### DELETE `/psychological-states/<state_id>/`

Delete a psychological state. Teacher/Admin/Supervisor only.

**Response:** `204 No Content`

### GET `/psychological-state-templates/`

List all psychological state templates.

**Response (200):**
```json
[
  { "id": 1, "name": "Anxiety", "comment": "General anxiety assessment" },
  { "id": 2, "name": "Motivation", "comment": "Student motivation level" }
]
```

---

## 5. Teachers

### GET `/teachers/`

List all teachers. Teacher/Admin/Supervisor only.

**Response (200):**
```json
[
  {
    "id": 1,
    "user": { /* UserSerializer */ },
    "gender": "M",
    "academic_degree": "PhD",
    "employment_type": "full_time",
    "occupation": "Mathematics",
    "working_hours": 40
  }
]
```

### GET `/teachers/<user_id>/`

Teacher detail by **CustomUser.id**. Includes assignments and subjects.

**Response (200):**
```json
{
  "id": 1,
  "user": { /* UserSerializer */ },
  "gender": "M",
  "academic_degree": "PhD",
  "employment_type": "full_time",
  "occupation": "Mathematics",
  "working_hours": 40,
  "assignments": [
    {
      "id": 1,
      "offering": {
        "id": 10,
        "subject": { "id": 3, "name": "Math", "language_group": "rus", "status": "active", "added_by": { /* ... */ } },
        "class_group": { /* ClassGroupSerializer */ },
        "academic_year": { /* ... */ },
        "grading_strategy": "average",
        "max_points": 100
      },
      "teacher": 1,
      "role": "primary"
    }
  ],
  "subjects": [
    { "id": 3, "name": "Math", "language_group": "rus", "status": "active", "added_by": { /* ... */ } }
  ]
}
```

### PATCH `/teachers/<teacher_pk>/update/`

Update teacher profile. **Admin-only.** Uses `Teacher.pk`.

**Request:**
```json
{
  "first_name": "New Name",
  "gender": "F",
  "academic_degree": "Masters",
  "employment_type": "part_time",
  "occupation": "Physics"
}
```

**Editable fields:** `email`, `first_name`, `last_name`, `phone_number`, `date_of_birth`, `address`, `gender`, `academic_degree`, `employment_type`, `occupation`

### GET `/parent/teachers/`

List teachers of the current parent's children. **Parent-only.**

Same response shape as `/teachers/`.

---

## 6. Subjects

### GET `/subjects/?status=active&year=1&lang=kaz`

List subjects. Role-filtered automatically:
- **Admin/Supervisor/Principal** — all subjects
- **Teacher** — only assigned subjects
- **Parent** — only children's subjects

**Query params:**
- `status` — `active` (default), `archived`, `disabled`, `planned`, `all`
- `year` — academic year ID
- `lang` — `kaz`, `rus`, `eng`, or omit for all

**Response (200):**
```json
[
  {
    "id": 3,
    "name": "Mathematics",
    "language_group": "rus",
    "status": "active",
    "added_by": { /* UserSerializer */ }
  }
]
```

### POST `/subjects/new/`

Create a subject with optional class group offerings. Teacher/Admin/Supervisor only.

**Request:**
```json
{
  "name": "Physics",
  "language_group": "rus",
  "status": "active",
  "academic_year": 1,
  "class_groups": [3, 5, 7]
}
```

**Response (201):** `SubjectSerializer` of created subject.

### GET `/subjects/<id>/`

Subject detail with offerings, student count, lesson count, primary teacher.

**Response (200):**
```json
{
  "id": 3,
  "name": "Mathematics",
  "language_group": "rus",
  "status": "active",
  "added_by": { /* UserSerializer */ },
  "offerings": [ /* SubjectOfferingSerializer[] */ ],
  "students_count": 45,
  "lessons_count": 12,
  "primary_teacher": { /* TeacherListSerializer or null */ }
}
```

### GET `/subjects/<id>/grades/?quarter=1`

Grade data for a subject by quarter.

**Query params:** `quarter` — 1-4 (default 1)

**Response (200):**
```json
{
  "quarter": 1,
  "students_count": 30,
  "lessons_count": 12,
  "average_subject_points": 72.5,
  "completion_percent": 85.0,
  "top_grades": [
    {
      "grade": 95.2,
      "student_name": "Айдана Сериккызы",
      "student_id": 5,
      "user_id": 12
    }
  ],
  "lessons": [
    { "id": 1, "title": "Introduction", "date": "2026-01-15", "order": 1 }
  ],
  "lesson_avgs": {
    "1": { "5": 95.2, "8": 82.0 }
  }
}
```

> `lesson_avgs` keys: `{ "<lesson_id>": { "<student_id>": grade } }`

### POST `/subjects/<id>/status/`

Change subject status. Teacher/Admin/Supervisor only.

**Request:**
```json
{ "action": "archive" }
```

**Actions:** `archive`, `activate`, `plan`

**Response (200):** Updated `SubjectSerializer`.

### DELETE `/subjects/<id>/delete/`

Delete a subject. **Admin-only.**

**Response:** `204 No Content`

### GET `/my-subjects/?status=active`

List current teacher's assigned subjects. Auth required.

Same response as `/subjects/`.

---

## 7. Lessons

**Roles:** Teacher/Admin/Supervisor can create, modify, and delete lessons. Any authenticated user can view lessons they have access to.

### GET `/lessons/?class_group=1&subject=Math&quarter=2`

List lessons with optional filters.

**Query params (all optional):**
- `class_group` — class group ID (or `all`)
- `subject` — subject name (or `all`)
- `quarter` — quarter number 1-4 (or `all`)

**Response (200):**
```json
[
  {
    "id": 1,
    "title": "Introduction to Algebra",
    "description": "Basic algebraic expressions",
    "date": "2026-02-10",
    "order": 1,
    "status": "completed",
    "quarter": 1,
    "unit": 1,
    "offering": {
      "id": 10,
      "subject_name": "Mathematics",
      "class_group_name": "7A",
      "academic_year_label": "2025-2026"
    },
    "graded_percent": 85,
    "created_at": "2026-02-01T10:00:00+05:00",
    "updated_at": "2026-02-10T14:30:00+05:00"
  }
]
```

### POST `/lessons/`

Create a lesson. Teacher/Admin/Supervisor only. Teachers can only create for their own offerings.

**Request:**
```json
{
  "offering": 10,
  "title": "Quadratic Equations",
  "description": "Solving quadratic equations",
  "date": "2026-03-01",
  "order": 2,
  "status": "pending",
  "quarter": 1,
  "unit": 3
}
```

**Response (201):** Full `LessonDetailSerializer` (see detail endpoint below).

### GET `/lessons/<id>/`

Lesson detail with topics (nested subtopics), enrolled students, and per-student grades.

**Response (200):**
```json
{
  "id": 1,
  "title": "Introduction to Algebra",
  "description": "...",
  "date": "2026-02-10",
  "order": 1,
  "status": "completed",
  "quarter": 1,
  "unit": 1,
  "offering": {
    "id": 10,
    "subject_name": "Mathematics",
    "class_group_name": "7A",
    "academic_year_label": "2025-2026"
  },
  "topics": [
    {
      "id": 1,
      "title": "Variables",
      "order": 1,
      "weight": "50.00",
      "comment_template": "Understands variable concepts",
      "subtopics": [
        { "id": 5, "title": "Constants", "order": 1, "weight": "50.00", "comment_template": "" },
        { "id": 6, "title": "Expressions", "order": 2, "weight": "50.00", "comment_template": "" }
      ]
    },
    {
      "id": 2,
      "title": "Equations",
      "order": 2,
      "weight": "50.00",
      "comment_template": "",
      "subtopics": []
    }
  ],
  "students": [
    { "id": 5, "user_id": 12, "full_name": "Айдана Сериккызы", "username": "aidana@school.kz" }
  ],
  "student_grades": {
    "12": {
      "grade_total": 75.0,
      "1": { "grade": 80.0, "comment": "Good work", "comment_selected": false },
      "2": { "grade": 70.0, "comment": "", "comment_selected": false }
    }
  },
  "created_at": "...",
  "updated_at": "..."
}
```

> `student_grades` keys are **user IDs** (strings). Each entry has `grade_total` plus per-topic entries keyed by **topic ID**.

### DELETE `/lessons/<id>/`

Delete a lesson. Teacher/Admin/Supervisor who can modify.

**Response:** `204 No Content`

---

## 8. Topics

### POST `/lessons/<lesson_id>/topics/`

Create a parent topic. Auto-assigns order and recalculates all topic weights equally.

**Request:**
```json
{
  "title": "New Topic",
  "comment_template": "Optional comment template"
}
```

**Response (201):**
```json
{
  "id": 3,
  "title": "New Topic",
  "order": 3,
  "weight": "33.33",
  "comment_template": "Optional comment template",
  "subtopics": []
}
```

### PATCH `/topics/<id>/`

Update a topic's title, weight, or comment template.

**Request (partial):**
```json
{
  "title": "Updated Title",
  "weight": "40.00"
}
```

**Response (200):** Updated `TopicSerializer`.

### DELETE `/topics/<id>/`

Delete a topic. Remaining sibling weights are rebalanced equally.

**Response:** `204 No Content`

### POST `/lessons/<lesson_id>/topics/distribute-weights/`

Distribute all parent topic weights equally (100 / count).

**Response (200):** Array of all parent `TopicSerializer` with updated weights.

---

## 9. Subtopics

### POST `/lessons/<lesson_id>/subtopics/`

Create a subtopic under a parent topic. Auto-assigns order and distributes subtopic weights equally.

**Request:**
```json
{
  "parent": 1,
  "title": "New Subtopic"
}
```

**Validation:**
- `parent` must belong to the specified lesson
- `parent` must be a parent topic (not itself a subtopic)

**Response (201):**
```json
{
  "id": 7,
  "title": "New Subtopic",
  "order": 3,
  "weight": "33.33",
  "comment_template": ""
}
```

### PATCH `/subtopics/<id>/`

Update a subtopic's title, weight, or comment template.

**Request (partial):**
```json
{ "title": "Updated Subtopic" }
```

**Response (200):** Updated `SubtopicSerializer`.

### POST `/lessons/<lesson_id>/subtopics/distribute-weights/`

Redistribute all subtopic weights equally under each parent topic. Applies rounding correction to the last subtopic.

**Response (200):** Array of all parent `TopicSerializer` with nested subtopics showing updated weights.

---

## 10. Grading

### GET `/lessons/<lesson_id>/grading/`

Get full grading page data. Teacher/Admin/Supervisor who can modify the lesson.

**Response (200):**
```json
{
  "id": 1,
  "title": "Introduction to Algebra",
  "quarter": 1,
  "unit": 1,
  "status": "completed",
  "topics": [ /* TopicSerializer[] with nested subtopics */ ],
  "students": [
    { "id": 5, "user_id": 12, "full_name": "Айдана Сериккызы" }
  ],
  "topic_grade_map": {
    "12-1": { "grade": 80.0, "comment": "Good", "comment_selected": false },
    "12-5": { "grade": 100.0, "comment": "", "comment_selected": false }
  },
  "student_grades": {
    "12": 75.0
  },
  "merged_comment_map": {
    "12": "Full merged comment text..."
  },
  "selected_comments_map": {
    "15": "Selected topic comment"
  },
  "comment_templates": {
    "1": "Understands variable concepts",
    "2": ""
  },
  "comment_modes": {
    "12": "merged",
    "15": "selected",
    "18": null
  }
}
```

> `topic_grade_map` keys: `"<user_id>-<topic_id>"`
> `student_grades`, `merged_comment_map`, `selected_comments_map`, `comment_modes` keys: `"<user_id>"`

### POST `/lessons/<lesson_id>/grading/`

Submit grades for a student. Creates or updates `TopicGrade` records.

**Request:**
```json
{
  "student_id": 12,
  "comment_mode": "merged",
  "topics": {
    "1": {
      "covered": true,
      "comment": "Good understanding of variables",
      "comment_selected": false
    },
    "2": {
      "covered": false,
      "comment": "Needs more practice",
      "comment_selected": false
    }
  },
  "subtopics": {
    "5": { "covered": true, "comment": "Constants mastered", "comment_selected": false },
    "6": { "covered": true, "comment": "Expression basics ok", "comment_selected": true }
  }
}
```

**Fields:**
- `student_id` — **CustomUser.id** of the student
- `comment_mode` — `"merged"` (aggregates all comments into one), `"selected"` (uses per-topic selected comments), or `"none"`
- `topics` — dict keyed by parent topic ID
- `subtopics` — dict keyed by subtopic ID

**Grade logic:**
- Subtopics: `covered: true` → grade 100, `covered: false` → grade 0
- Parent topics with subtopics: grade = weighted average of subtopic grades
- Parent topics without subtopics: uses `covered` directly

**Response (200):**
```json
{ "detail": "Grades saved successfully." }
```

### PATCH `/lessons/<lesson_id>/grading/`

Same as POST — updates existing grades. Same request format and logic.

### DELETE `/lessons/<lesson_id>/grading/<student_user_id>/`

Delete all grades and merged comments for a student on a lesson.

**Response:** `204 No Content`

---

## 11. Notifications

### GET `/notifications/`

List current user's notifications, ordered by newest first. Paginated (page size 20).

**Response (200):**
```json
{
  "count": 25,
  "next": "http://localhost:8000/api/v1/notifications/?page=2",
  "previous": null,
  "results": [
    {
      "id": 50,
      "action": "grading",
      "send_time": "2026-04-28T14:30:00+05:00",
      "message": "The grade for the lesson 'Introduction to Algebra' has been released"
    },
    {
      "id": 49,
      "action": "register",
      "send_time": "2026-04-27T09:00:00+05:00",
      "message": "User registered successfully"
    },
    {
      "id": 48,
      "action": "psychological_state",
      "send_time": "2026-04-26T11:15:00+05:00",
      "message": "dr.smith updated the information about psychological state"
    }
  ]
}
```

**Action types:** `register`, `login`, `grading`, `psychological_state`

### GET `/notifications/<id>/`

Single notification detail. Only accessible by the notification's owner.

**Response (200):**
```json
{
  "id": 50,
  "action": "grading",
  "send_time": "2026-04-28T14:30:00+05:00",
  "message": "The grade for the lesson 'Introduction to Algebra' has been released"
}
```

### GET `/notifications/count/`

Get notification count for the current user.

**Response (200):**
```json
{ "count": 25 }
```

### DELETE `/notifications/<id>/delete/`

Delete a notification. Only the owner can delete.

**Response:** `204 No Content`

---

## 12. Enrollments

### GET `/enrollments/?year=1&class_group=3&student=5`

List enrollments. Teacher/Admin/Supervisor only.

**Query params (all optional):**
- `year` — academic year ID
- `class_group` — class group ID
- `student` — student ID

**Response (200):**
```json
[
  {
    "id": 1,
    "student": 5,
    "class_group": { /* ClassGroupSerializer */ },
    "academic_year": { /* AcademicYearSerializer */ },
    "status": "active",
    "start_date": "2025-09-01",
    "end_date": null
  }
]
```

---

## Error Handling

All errors follow a consistent format:

**Validation errors (400):**
```json
{
  "field_name": ["Error message"]
}
```

**Permission denied (403):**
```json
{
  "detail": "You do not have permission to perform this action."
}
```

**Not found (404):**
```json
{
  "detail": "Not found."
}
```

**Unauthorized (401):**
```json
{
  "detail": "Given token not valid for any token type",
  "code": "token_not_valid"
}
```

---

## Recommended Token Management (TypeScript)

```typescript
const API_BASE = 'http://localhost:8000/api/v1';

let accessToken: string | null = localStorage.getItem('access');
let refreshToken: string | null = localStorage.getItem('refresh');

async function apiRequest(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let response = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (response.status === 401 && refreshToken) {
    const refreshRes = await fetch(`${API_BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: refreshToken }),
    });

    if (refreshRes.ok) {
      const data = await refreshRes.json();
      accessToken = data.access;
      refreshToken = data.refresh;
      localStorage.setItem('access', data.access);
      localStorage.setItem('refresh', data.refresh);

      headers.set('Authorization', `Bearer ${accessToken}`);
      response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } else {
      // Refresh failed — clear tokens, redirect to login
      accessToken = null;
      refreshToken = null;
      localStorage.removeItem('access');
      localStorage.removeItem('refresh');
      window.location.href = '/login';
    }
  }

  return response;
}
```

---

## Role Reference

| Role | List students | Edit profiles | Create subjects | Create lessons | Grade students | Manage psych states | View notifications |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Admin | yes | yes | yes | yes | yes | yes | own |
| Supervisor | yes | yes | yes | yes | yes | yes | own |
| Principal | yes | no | no | no | no | yes | own |
| Teacher | yes | no | yes | yes (own) | yes (own) | yes | own |
| HomeroomTeacher | yes | no | yes | yes (own) | yes (own) | yes | own |
| Parent | no | no | no | no | no | no | own |
| Student | no | no | no | no | no | no | own |

## Endpoint Summary (51 total)

| Module | Count | Prefix |
|--------|:-----:|--------|
| Auth | 10 | `/auth/` |
| Dashboard | 1 | `/dashboard/` |
| Academic Structure | 2 | `/academic-years/`, `/class-groups/` |
| Students | 6 | `/students/`, `/psychological-*` |
| Teachers | 4 | `/teachers/`, `/parent/teachers/` |
| Subjects | 7 | `/subjects/`, `/my-subjects/` |
| Enrollments | 1 | `/enrollments/` |
| Lessons | 4 | `/lessons/` |
| Topics | 3 | `/lessons/.../topics/`, `/topics/` |
| Subtopics | 3 | `/lessons/.../subtopics/`, `/subtopics/` |
| Grading | 6 | `/lessons/.../grading/` |
| Notifications | 4 | `/notifications/` |
