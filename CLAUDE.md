# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Qadam Analytics is a school management and grading platform built with Django 5.2 / Python 3.13. It uses server-rendered HTML templates (Argon Dashboard Bootstrap theme), PostgreSQL 14, and Docker for deployment.

## Development Commands

```bash
# Start dev database (PostgreSQL on port 5433)
docker compose -f docker-compose.dev.yml up -d db

# Start dev object storage (MinIO: S3 API on 9000, console on 9001)
# minio-init creates the private bucket; required — media storage is always S3
docker compose -f docker-compose.dev.yml up -d minio minio-init

# Run Django dev server locally (requires .env with DB_NAME, DB_USER, DB_PASSWORD, DB_HOST=localhost,
# DB_PORT=5433, S3_ENDPOINT_URL=http://localhost:9000, S3_ACCESS_KEY, S3_SECRET_KEY; MinIO must be up)
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Run tests
python manage.py test
python manage.py test apps.home          # single app
python manage.py test apps.home.tests.TestClassName.test_method  # single test

# Static files (for production/Docker)
python manage.py collectstatic --noinput

# Code style
pycodestyle apps/ core/
autopep8 --in-place --recursive apps/ core/

# Docker build & push (uses GHCR, tags by git SHA)
make build
make push
```

## Architecture

### Django Apps (under `apps/`)

- **authentication** — Custom user model (`CustomUser` extending AbstractUser), role management via Django Groups. Roles: Admin, Teacher, HomeroomTeacher, Student, Supervisor, Principal, Parent. The `.role` property returns the user's primary group name in lowercase for backward compatibility. Profile models (`Student`, `Teacher`, `Parent`, `Supervisor`) are OneToOne with `CustomUser` and hold domain-specific fields. Service layer in `services.py` (`AccountService`).
- **home** — Dashboards, profile pages, admin operations. Core academic models: `AcademicYear`, `ClassGroup`, `Subject`, `SubjectOffering`, `Enrollment`, `TeachingAssignment`. `SubjectOffering` is the central entity tying Subject + ClassGroup + AcademicYear together with a unique constraint; it also holds `grading_strategy` (average/weighted/cumulative). `TeachingAssignment` assigns teachers to offerings with a role field (primary/assistant/substitute). Uses repository pattern in `repo/` (students.py, teachers.py, subject.py).
- **lesson** — Grading system. Models: `Lesson`, `Topic` (self-referential for subtopics), `TopicGrade`. Grade calculation: `lesson_grade = SUM(topic_weight * topic_grade)` across parent topics; subtopics feed into their parent topic's grade via weighted average. Supports quarters (1-4) and units (1-15). `QuarterGrader` model is deprecated — quarter averages are now computed dynamically.
- **notification** — In-database notifications + email. Notification subtypes: `RegisterNotify`, `LoginNotify`, `GradingNotify`, `PsychologicalNotify`. Uses a context processor (`notifications_context`) to inject `notifications` and `notifications_count` globally into templates.

### Key Patterns

- **3-tier permission model**:
  1. Route-level: `@role_required('teacher', 'admin')` decorator in `core/decorators.py` — maps lowercase role names to Django Group names.
  2. Object-level: helper functions in `core/permissions.py` (e.g., `can_access_student()`, `can_grade_student()`) — Admin, Supervisor, and Principal groups bypass these checks.
  3. View-level: views further filter querysets (e.g., a teacher only sees their own offerings).
- **Repository pattern**: Data access in `apps/home/repo/` separates queries from views.
- **Service layer**: `AccountService` in authentication handles auth logic, email sending, verification codes.
- **Signal-based side effects**: avatar file cleanup on upload, registration email + notification creation on user save, auto-assignment of the active `AcademicYear` to new students.
- **Templates**: All in `apps/templates/`, with layouts in `layouts/`, reusable partials in `includes/`.
- **Static assets**: `apps/static/` — custom JS in `js/`, Argon Dashboard theme in `assets/`.

### URL Structure

| Prefix             | App              |
|--------------------|------------------|
| `/`                | main page        |
| `/login/`, `/register/`, `/logout/`, `/reset/` | authentication |
| `/pages/`          | home (dashboards)|
| `/lessons/`        | lesson (grading) |
| `/notifications/`  | notification     |
| `/admin/`          | Django admin     |
| `/healthz`         | health check     |

### Configuration

- Settings: `core/settings.py` — uses `python-decouple` for env vars
- Auth model: `authentication.CustomUser`
- Database: PostgreSQL (env vars: DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT)
- Timezone: Asia/Almaty
- Static files served by WhiteNoise middleware; in Docker served from `/vol/static` via Nginx
- Media files: always S3/MinIO — there is no local-disk mode. `S3_ENDPOINT_URL` is
  required and settings raise `ImproperlyConfigured` at startup without it, so MinIO
  must be running before Django will start (env vars: S3_ENDPOINT_URL, S3_BUCKET_NAME,
  S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION, S3_URL_EXPIRE).
  The bucket is private — `FileField.url` returns a presigned link valid for
  `S3_URL_EXPIRE` seconds, signed against the public origin that Nginx proxies
  to the `minio` container at `/<bucket>/`. Note that `.path` is unavailable on
  S3 storage; use `.name` plus `storage.exists()` instead.

### Scripts (`scripts/`)

Bulk data import utilities (XLS user imports, subject seeding, grading scripts, Google Sheets integration). Run as standalone Python scripts, not Django management commands.
