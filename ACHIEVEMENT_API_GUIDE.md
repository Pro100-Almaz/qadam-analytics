# Achievement & Development API — Frontend Integration Guide

**Base URL:** `http://localhost:8000/api/v1/`

All endpoints require `Authorization: Bearer <access_token>`. File uploads use `Content-Type: multipart/form-data`.

---

## 1. Achievements

Tracks student accomplishments split by academic year across 4 categories:

| Category | Key Fields |
|----------|-----------|
| `olympiad` | subject, award_type, place, description |
| `additional_education` | award_type, place, description |
| `extracurricular` | role, duration, description |
| `project` | award_type, place, description |

### GET `/students/<student_pk>/achievements/`

List achievements for a student.

**Query params (all optional):**
- `year` — academic year ID
- `category` — `olympiad`, `additional_education`, `extracurricular`, `project`

**Response (200):**
```json
[
  {
    "id": 1,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "category": "olympiad",
    "subject_name": "Mathematics",
    "award_type": "Gold Medal",
    "place": "National",
    "role": "",
    "duration": "",
    "description": "1st place in National Math Olympiad",
    "certificate": "/media/achievements/certificates/math_cert.pdf",
    "created_at": "2026-03-15T10:00:00+05:00",
    "updated_at": "2026-03-15T10:00:00+05:00"
  },
  {
    "id": 2,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "category": "extracurricular",
    "subject_name": null,
    "award_type": "",
    "place": "",
    "role": "Club President",
    "duration": "Sep 2025 – May 2026",
    "description": "Led the debate club, organized 3 inter-school tournaments",
    "certificate": null,
    "created_at": "2026-02-10T09:00:00+05:00",
    "updated_at": "2026-02-10T09:00:00+05:00"
  }
]
```

### POST `/students/<student_pk>/achievements/`

Create an achievement. **Teacher/Admin/Supervisor only.**

**Content-Type:** `multipart/form-data` (for certificate upload) or `application/json` (without file).

**Request fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `academic_year` | integer | yes | AcademicYear ID |
| `category` | string | yes | `olympiad`, `additional_education`, `extracurricular`, `project` |
| `subject` | integer | no | Subject ID — relevant for `olympiad` |
| `award_type` | string | no | For olympiad, additional_education, project |
| `place` | string | no | e.g. "City", "Regional", "National", "International" |
| `role` | string | **yes for extracurricular** | e.g. "Староста", "Club President" |
| `duration` | string | no | e.g. "Sep 2025 – May 2026" |
| `description` | string | no | Description or result/comments |
| `certificate` | file | no | PDF, image, or any document |

**Example — Olympiad:**
```json
{
  "academic_year": 1,
  "category": "olympiad",
  "subject": 3,
  "award_type": "Gold Medal",
  "place": "National",
  "description": "1st place in National Math Olympiad"
}
```

**Example — Extracurricular:**
```json
{
  "academic_year": 1,
  "category": "extracurricular",
  "role": "Club President",
  "duration": "Sep 2025 – May 2026",
  "description": "Led the debate club"
}
```

**Example — Additional Education (multipart/form-data):**
```
academic_year: 1
category: additional_education
award_type: 1st Place
place: City
description: Chess tournament winner
certificate: [file]
```

**Response (201):** Full achievement object (same shape as list item).

**Validation errors:**
- `400` — `{"role": ["Role is required for extracurricular achievements."]}`

---

### GET `/achievements/<id>/`

Get single achievement detail. Requires access to the student.

**Response (200):** Same shape as list item.

### PATCH `/achievements/<id>/`

Update an achievement. **Teacher/Admin/Supervisor only.** Partial update — only send changed fields.

**Request (example):**
```json
{
  "award_type": "Silver Medal",
  "description": "Updated description"
}
```

**Response (200):** Updated achievement object.

### DELETE `/achievements/<id>/`

Delete an achievement. **Teacher/Admin/Supervisor only.**

**Response:** `204 No Content`

### GET `/achievements/<id>/download/`

Download the certificate file. Returns the file as an attachment.

**Response headers:**
```
Content-Type: application/pdf (or detected MIME type)
Content-Disposition: attachment; filename="math_cert.pdf"
```

**Errors:**
- `404` — `{"detail": "No certificate file attached to this achievement."}` or `{"detail": "Certificate file not found on disk."}`

---

## 2. Reading List (Development)

Tracks books read by students — per month, per academic year.

### GET `/students/<student_pk>/reading-entries/`

List reading entries for a student.

**Query params (all optional):**
- `year` — academic year ID
- `month` — 1-12

**Response (200):**
```json
[
  {
    "id": 1,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "title": "Маленький Принц",
    "cover": "/media/achievements/book_covers/prince.jpg",
    "month": 9,
    "pages_read": 96,
    "test_score": 85.0,
    "created_at": "2026-09-20T10:00:00+05:00"
  },
  {
    "id": 2,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "title": "Война и Мир",
    "cover": null,
    "month": 10,
    "pages_read": 250,
    "test_score": null,
    "created_at": "2026-10-15T10:00:00+05:00"
  }
]
```

### POST `/students/<student_pk>/reading-entries/`

Create a reading entry. **Teacher/Admin/Supervisor only.**

**Content-Type:** `multipart/form-data` (for book cover upload) or `application/json`.

**Request fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `academic_year` | integer | yes | AcademicYear ID |
| `title` | string | yes | Book title |
| `cover` | image file | no | Book cover photo (JPG/PNG) |
| `month` | integer | yes | 1-12 |
| `pages_read` | integer | no | Default 0 |
| `test_score` | float | no | 0-100, null if no test taken |

**Example (multipart/form-data):**
```
academic_year: 1
title: Маленький Принц
month: 9
pages_read: 96
test_score: 85.0
cover: [image file]
```

**Response (201):** Full reading entry object.

---

### GET `/reading-entries/<id>/`

Single reading entry detail.

**Response (200):** Same shape as list item.

### PATCH `/reading-entries/<id>/`

Update a reading entry. **Teacher/Admin/Supervisor only.** Partial update.

**Request (example):**
```json
{
  "pages_read": 120,
  "test_score": 90.5
}
```

**Response (200):** Updated reading entry.

### DELETE `/reading-entries/<id>/`

Delete a reading entry. **Teacher/Admin/Supervisor only.**

**Response:** `204 No Content`

---

## 3. Clubs (Development)

Tracks club/circle participation per month with session attendance.

### GET `/students/<student_pk>/club-entries/`

List club entries for a student.

**Query params (all optional):**
- `year` — academic year ID
- `month` — 1-12
- `club_name` — partial match (case-insensitive)

**Response (200):**
```json
[
  {
    "id": 1,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "month": 9,
    "club_name": "Chess Club",
    "plan": "Learn basic openings and endgame strategies",
    "criteria": "Participate in at least 2 mini-tournaments",
    "total_sessions": 10,
    "attended_sessions": 8,
    "comments": "Good progress, showing interest in Sicilian Defense",
    "created_at": "2026-09-30T10:00:00+05:00"
  },
  {
    "id": 2,
    "student": { "id": 5, "full_name": "Айдана Сериккызы" },
    "academic_year": "2025-2026",
    "month": 10,
    "club_name": "Chess Club",
    "plan": "Advanced tactics and tournament preparation",
    "criteria": "Win at least 1 mini-tournament game",
    "total_sessions": 12,
    "attended_sessions": 11,
    "comments": "Excellent attendance, won 2 games",
    "created_at": "2026-10-31T10:00:00+05:00"
  }
]
```

### POST `/students/<student_pk>/club-entries/`

Create a club entry. **Teacher/Admin/Supervisor only.**

**Request fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `academic_year` | integer | yes | AcademicYear ID |
| `month` | integer | yes | 1-12 |
| `club_name` | string | yes | e.g. "Chess Club", "Robotics" |
| `plan` | string | no | Monthly plan |
| `criteria` | string | no | Success criteria |
| `total_sessions` | integer | no | Total sessions in the month (default 0) |
| `attended_sessions` | integer | no | Sessions attended (default 0, must be <= total) |
| `comments` | string | no | Teacher comments |

**Example:**
```json
{
  "academic_year": 1,
  "month": 9,
  "club_name": "Chess Club",
  "plan": "Learn basic openings",
  "criteria": "Participate in mini-tournament",
  "total_sessions": 10,
  "attended_sessions": 8,
  "comments": "Good progress"
}
```

**Response (201):** Full club entry object.

**Validation errors:**
- `400` — `{"attended_sessions": ["Attended sessions cannot exceed total sessions."]}`

---

### GET `/club-entries/<id>/`

Single club entry detail.

**Response (200):** Same shape as list item.

### PATCH `/club-entries/<id>/`

Update a club entry. **Teacher/Admin/Supervisor only.** Partial update.

**Request (example):**
```json
{
  "attended_sessions": 10,
  "comments": "Perfect attendance this month"
}
```

**Response (200):** Updated club entry.

### DELETE `/club-entries/<id>/`

Delete a club entry. **Teacher/Admin/Supervisor only.**

**Response:** `204 No Content`

---

## Data Model Summary

```
Student
 ├── Achievement (1:N)
 │     ├── category: olympiad | additional_education | extracurricular | project
 │     ├── academic_year (FK)
 │     ├── subject (FK, optional — for olympiad)
 │     ├── award_type, place (for olympiad, additional_education, project)
 │     ├── role, duration (for extracurricular)
 │     ├── description
 │     └── certificate (file upload)
 │
 ├── ReadingEntry (1:N)
 │     ├── academic_year (FK)
 │     ├── title, cover (image)
 │     ├── month (1-12)
 │     ├── pages_read
 │     └── test_score (nullable)
 │
 └── ClubEntry (1:N)
       ├── academic_year (FK)
       ├── month (1-12)
       ├── club_name
       ├── plan, criteria
       ├── total_sessions, attended_sessions
       └── comments
```

## Endpoint Summary (11 endpoints)

| # | Method | Endpoint | Auth |
|---|--------|----------|------|
| 1 | GET | `/students/<pk>/achievements/` | Any (with student access) |
| 2 | POST | `/students/<pk>/achievements/` | Teacher/Admin/Supervisor |
| 3 | GET | `/achievements/<pk>/` | Any (with student access) |
| 4 | PATCH | `/achievements/<pk>/` | Teacher/Admin/Supervisor |
| 5 | DELETE | `/achievements/<pk>/` | Teacher/Admin/Supervisor |
| 6 | GET | `/achievements/<pk>/download/` | Any (with student access) |
| 7 | GET | `/students/<pk>/reading-entries/` | Any (with student access) |
| 8 | POST | `/students/<pk>/reading-entries/` | Teacher/Admin/Supervisor |
| 9 | GET/PATCH/DELETE | `/reading-entries/<pk>/` | View: any / Modify: Teacher/Admin/Supervisor |
| 10 | GET | `/students/<pk>/club-entries/` | Any (with student access) |
| 11 | POST | `/students/<pk>/club-entries/` | Teacher/Admin/Supervisor |
| 12 | GET/PATCH/DELETE | `/club-entries/<pk>/` | View: any / Modify: Teacher/Admin/Supervisor |

## Role Permissions

| Role | View | Create/Edit/Delete |
|------|:----:|:------------------:|
| Admin | yes | yes |
| Supervisor | yes | yes |
| Principal | yes | no |
| Teacher | yes (own students) | yes (own students) |
| HomeroomTeacher | yes (own students) | yes (own students) |
| Parent | yes (own children) | no |
| Student | yes (own) | no |
