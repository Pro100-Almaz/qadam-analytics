# Qadam Analytics

Educational analytics and grading management platform for private schools in Kazakhstan.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [User Roles & Permissions](#user-roles--permissions)
- [Features](#features)
- [Setup & Installation](#setup--installation)
- [API Endpoints](#api-endpoints)
- [External Integrations](#external-integrations)
- [AI Student Reports](#ai-student-reports)
- [Development](#development)

---

## Overview

Qadam Analytics is a comprehensive school management system that provides:

- **Grading System** - Hierarchical topic-based grading with weighted scores
- **Student Analytics** - Progress tracking and performance metrics
- **Parent Portal** - Real-time access to student grades and psychological assessments
- **Teacher Dashboard** - Lesson planning, grading interface, and student management
- **Psychological Wellness** - Mental health tracking with 5-star rating system

---

## Architecture

### High-Level Architecture

```
                              CLIENTS
                   (Browser / Mobile / Parent App)
                                 |
                                 v
+------------------------------------------------------------------------+
|                        NGINX (Reverse Proxy)                            |
|                  - SSL Termination                                      |
|                  - Static File Serving (/vol/static)                    |
|                  - Load Balancing                                       |
+------------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------------+
|                       DJANGO APPLICATION                                |
|                   (Gunicorn - 3 Workers)                                |
|  +--------+ +--------+ +--------+ +--------+ +----------+ +---------+  |
|  |  Auth  | |  Home  | | Lesson | | Notif  | |Achievement| |Student  |  |
|  |  App   | |  App   | |  App   | |  App   | |   App     | |Report   |  |
|  +--------+ +--------+ +--------+ +--------+ +----------+ +---------+  |
+------------------------------------------------------------------------+
         |                   |                    |              |
         v                   v                    v              v
+--------------+    +--------------+     +--------------+ +-----------+
|  PostgreSQL  |    |    AWS S3    |     | Google Sheets| |  OpenAI   |
|   Database   |    |   (Media)    |     |   (Import)   | |    API    |
|  (14-alpine) |    |qadam-avatars |     |              | |(gpt-4o-m) |
+--------------+    +--------------+     +--------------+ +-----------+
                                                               ^
+--------------+    +--------------+                           |
|    Redis     |    |   Celery     |---(async report generation)
|   (Cache +   |<---|   Worker     |
|    Broker)   |    +--------------+
+--------------+
```

### Application Architecture

```
+------------------------------------------------------------------------+
|                         PRESENTATION LAYER                              |
|  +------------------------------------------------------------------+  |
|  |                   Django Templates (Jinja2)                       |  |
|  |  - home/        (Dashboard views)                                 |  |
|  |  - lesson/      (Grading interface)                               |  |
|  |  - accounts/    (Login/Register)                                  |  |
|  |  - includes/    (Reusable components: sidenav, navbar)            |  |
|  +------------------------------------------------------------------+  |
+------------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------------+
|                          BUSINESS LAYER                                 |
|  +----------------+  +----------------+  +--------------------------+   |
|  | AccountService |  | GradingService |  |   NotificationService    |   |
|  | - authenticate |  | - calculate    |  |   - send_email           |   |
|  | - register     |  | - submit_grade |  |   - create_notification  |   |
|  | - reset_pass   |  | - update_topic |  |                          |   |
|  +----------------+  +----------------+  +--------------------------+   |
+------------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------------+
|                           DATA LAYER                                    |
|  +------------------------------------------------------------------+  |
|  |                    Django ORM Models                              |  |
|  |  CustomUser --+-- Student ---- Classroom ---- AcademicYear        |  |
|  |               +-- Teacher ---- Subject ------ Lesson -- Topic     |  |
|  |               +-- Parent                               +- Grade   |  |
|  |               +-- Supervisor                                      |  |
|  +------------------------------------------------------------------+  |
+------------------------------------------------------------------------+
```

### Grading System Architecture

```
Subject (e.g., "Mathematics 5A")
    |
    +-- Quarter 1
    |       +-- Lesson 1: "Introduction to Algebra"
    |       |       +-- Topic 1: "Variables" (weight: 40%)
    |       |       |       +-- Subtopic: "Naming" (weight: 50%)
    |       |       |       +-- Subtopic: "Types" (weight: 50%)
    |       |       +-- Topic 2: "Expressions" (weight: 60%)
    |       |
    |       +-- Lesson 2: "Linear Equations"
    |               +-- Topic 1: "Solving" (weight: 100%)
    |
    +-- Quarter 2
    |       +-- ...
    |
    +-- QuarterGrader (aggregates quarterly averages)

Grade Calculation:
+-----------------------------------------------------+
|  Student Grade = SUM(Topic.weight * TopicGrade.grade)|
|                                                     |
|  Example:                                           |
|  - Topic 1 (40%): Grade 85 -> 0.4 * 85 = 34        |
|  - Topic 2 (60%): Grade 90 -> 0.6 * 90 = 54        |
|  - Final Grade: 34 + 54 = 88                        |
+-----------------------------------------------------+
```

---

## Tech Stack

| Category | Technology |
|----------|------------|
| **Backend** | Django 5.2, Python 3.13 |
| **Database** | PostgreSQL 14 |
| **Server** | Gunicorn, Nginx |
| **Storage** | AWS S3 (boto3) |
| **Containerization** | Docker, Docker Compose |
| **Email** | Gmail SMTP |
| **External Data** | Google Sheets API (gspread) |
| **Task Queue** | Celery 5.4 + Redis 7 |
| **AI** | OpenAI API (gpt-4o-mini) |
| **PDF** | WeasyPrint 62 |
| **CSS Framework** | Bootstrap (Argon Dashboard) |

---

## Project Structure

```
qadam-analytics/
|-- core/                           # Django project configuration
|   |-- settings.py                 # Main settings (DB, AWS, Email)
|   |-- urls.py                     # Root URL routing
|   |-- decorators.py               # @role_required decorator
|   +-- credentials/                # Google Sheets API credentials
|
|-- apps/
|   |-- authentication/             # User & role management
|   |   |-- models.py               # CustomUser, Student, Teacher, Parent
|   |   |-- services.py             # AccountService (auth logic)
|   |   |-- views.py                # Login, Register, Password Reset
|   |   +-- forms.py                # SignUpForm, LoginForm
|   |
|   |-- home/                       # Dashboard & resource management
|   |   |-- models.py               # ClassRoom, Subject, AcademicYear
|   |   |-- views.py                # Main dashboard routing
|   |   +-- repo/                   # Repository pattern
|   |       |-- students.py         # Student CRUD operations
|   |       |-- teachers.py         # Teacher CRUD operations
|   |       +-- subject.py          # Subject management
|   |
|   |-- lesson/                     # Grading system
|   |   |-- models.py               # Lesson, Topic, TopicGrade
|   |   +-- views.py                # Grading interface
|   |
|   |-- achievement/                # Achievements, reading, clubs
|   |   |-- models.py               # Achievement, ReadingEntry, ClubEntry, Attachment
|   |   +-- api/                    # REST API (CRUD + file upload)
|   |
|   |-- student_report/             # AI-generated student reports
|   |   |-- models.py               # StudentReport (status, report_data JSON)
|   |   |-- tasks.py                # Celery task + email notification
|   |   |-- services/
|   |   |   |-- data_collector.py   # Gathers grades, psych, achievements
|   |   |   |-- prompt_builder.py   # OpenAI prompt construction
|   |   |   +-- generator.py        # OpenAI API call + JSON parsing
|   |   |-- api/
|   |   |   |-- views.py            # Generate, list, detail endpoints
|   |   |   |-- serializers.py      # Full + list serializers
|   |   |   |-- pdf_export.py       # WeasyPrint PDF rendering
|   |   |   +-- urls.py             # URL routing
|   |   +-- templates/
|   |       +-- student_report/
|   |           +-- report_pdf.html # A4 PDF template (Cyrillic)
|   |
|   |-- notification/               # Notification system
|   |   |-- models.py               # Notification types
|   |   +-- context_processors.py   # Global notification injection
|   |
|   |-- templates/                  # HTML templates
|   |   |-- home/                   # Dashboard templates
|   |   |-- lesson/                 # Grading templates
|   |   |-- accounts/               # Auth templates
|   |   +-- includes/               # Reusable components
|   |
|   +-- static/                     # CSS, JS, images
|
|-- scripts/                        # Data import utilities
|   |-- users/                      # User import from XLS
|   |-- grading/                    # Grade import scripts
|   +-- reading_data.py             # Google Sheets reader
|
|-- docker/
|   +-- entrypoint.sh               # Container startup script
|
|-- docker-compose.yml              # Production configuration
|-- docker-compose.dev.yml          # Development configuration
|-- Dockerfile                      # Container image definition
|-- requirements.txt                # Python dependencies
+-- Makefile                        # Build automation
```

---

## Database Schema

### Entity Relationship Diagram

```
+------------------+       +------------------+       +------------------+
|   CustomUser     |       |   AcademicYear   |       |   SchoolGroup    |
+------------------+       +------------------+       +------------------+
| id (PK)          |       | id (PK)          |       | id (PK)          |
| username         |       | year             |       | name             |
| email            |       | (e.g. 2024/2025) |       | avatar           |
| password         |       +--------+---------+       +------------------+
| role             |                |
| first_name       |                |
| last_name        |                v
| phone            |       +------------------+
| avatar           |       |    ClassRoom     |
| school           |       +------------------+
| dob              |       | id (PK)          |
+--------+---------+       | name             |
         |                 | capacity         |
         |                 | academic_year(FK)|
    +----+----+----+----+  +--------+---------+
    |         |    |    |           |
    v         v    v    v           |
+--------+ +--------+ +----------+  |
|Student | |Teacher | | Parent   |  |
+--------+ +--------+ +----------+  |
|user(1:1)| |user(1:1)| |user(1:1) |  |
|classroom|<|classroom| |students  |  |
|subjects | |subjects | |  (M2M)   |  |
|  (M2M)  | |  (M2M)  | +----------+  |
|school_  | |gender   |               |
|  group  | |degree   |               |
|academic | |employ_  |               |
|  _year  | |  type   |               |
+----+----+ +----+----+               |
     |           |                    |
     |           |    +---------------+
     |           |    |
     |           v    v
     |    +------------------+
     |    |     Subject      |
     |    +------------------+
     |    | id (PK)          |
     |    | name             |
     |    | language_group   |
     |    | status           |
     |    | progress         |
     |    | average_points   |
     |    | teacher (FK)     |<--- Teacher
     |    | academic_year(FK)|
     |    | students (M2M)   |<--- Student
     |    +--------+---------+
     |             |
     |             v
     |    +------------------+      +------------------+
     |    |     Lesson       |      |   LessonGroup    |
     |    +------------------+      +------------------+
     |    | id (PK)          |      | id (PK)          |
     |    | title            |<-----| name             |
     |    | description      |      +------------------+
     |    | quarter (1-4)    |
     |    | unit (1-15)      |
     |    | status           |
     |    | subject (FK)     |
     |    | group (FK)       |
     |    +--------+---------+
     |             |
     |             v
     |    +------------------+
     |    |      Topic       |
     |    +------------------+
     |    | id (PK)          |
     |    | title            |
     |    | weight (0-100%)  |
     |    | comment_template |
     |    | lesson (FK)      |
     |    | parent (FK, self)|---> Subtopics
     |    +--------+---------+
     |             |
     +-------------+
                   v
          +------------------+
          |   TopicGrade     |
          +------------------+
          | id (PK)          |
          | grade (0-100)    |
          | comment          |
          | topic (FK)       |
          | student (FK)     |
          +------------------+
```

### Model Details

#### Authentication Models

| Model | Key Fields | Relationships |
|-------|------------|---------------|
| `CustomUser` | role, phone, avatar, school, dob | Base for all users |
| `Student` | school_group, academic_year | -> User, Classroom, Subjects (M2M) |
| `Teacher` | gender, academic_degree, employment_type | -> User, Classroom, Subjects (M2M) |
| `Parent` | - | -> User, Students (M2M) |
| `Supervisor` | - | -> User |

#### Academic Models

| Model | Key Fields | Relationships |
|-------|------------|---------------|
| `AcademicYear` | year | <- Classrooms, Subjects, Students |
| `ClassRoom` | name, capacity | -> AcademicYear |
| `Subject` | name, language_group, status, progress | -> Teacher, AcademicYear, Students (M2M) |
| `QuarterGrader` | quarter, average_points | -> Subject |

#### Lesson Models

| Model | Key Fields | Relationships |
|-------|------------|---------------|
| `Lesson` | title, quarter, unit, status | -> Subject, LessonGroup |
| `Topic` | title, weight | -> Lesson, Parent (self) |
| `TopicGrade` | grade, comment | -> Topic, Student |

---

## User Roles & Permissions

### Role Hierarchy

```
+----------------------------------------------------------------+
|                         ADMIN                                   |
|              (Full system access, Django admin)                 |
+----------------------------------------------------------------+
|                       SUPERVISOR                                |
|         (School management, approve profile changes)            |
+----------------------------------------------------------------+
|     PRINCIPAL          |         HOMEROOM_TEACHER              |
|  (School oversight)    |    (Class management + Teaching)       |
+-----------------------------------------------------------------+
|                        TEACHER                                  |
|        (Lesson creation, grading, student management)           |
+----------------------------------------------------------------+
|       PARENT                    |           STUDENT             |
|  (View child's grades,          |    (View own grades,          |
|   psychological states)         |     profile)                  |
+---------------------------------+--------------------------------+
```

### Role Definitions

| Role | Code | Capabilities |
|------|------|--------------|
| **Admin** | `admin` | Full access, Django admin panel |
| **Supervisor** | `supervisor` | Manage teachers, approve changes, view all data |
| **Principal** | `principal` | School-wide oversight (partially implemented) |
| **Homeroom Teacher** | `homeroom_teacher` | Class management + teaching duties |
| **Teacher** | `teacher` | Create lessons, grade students, manage subjects |
| **Parent** | `parent` | View linked students' grades and assessments |
| **Student** | `student` | View own grades and profile |

### Permission Checking

```python
# In models (apps/authentication/models.py)
class CustomUser(AbstractUser):
    def is_teacher(self):
        return self.role == CustomUser.ROLE_TEACHER

    def is_admin(self):
        return self.role == CustomUser.ROLE_ADMIN

    def is_manager(self):  # Supervisor
        return self.role == CustomUser.ROLE_SUPERVISOR

# In views (using decorator)
from core.decorators import role_required

@login_required
@role_required('teacher', 'admin')
def grading(request, pk):
    ...
```

### Current Limitations (To Be Improved)

1. **No server-side role validation** on most views
2. **Template-only permission checks** that can be bypassed
3. **No object-level permissions** (e.g., teacher can only grade own subjects)
4. **Orphaned roles** (`principal`, `homeroom_teacher`) without full implementation

---

## Features

### 1. Multi-Role Dashboard

Each role sees a customized dashboard:

| Role | Dashboard Features |
|------|-------------------|
| **Teacher** | My subjects, lessons to grade, student list |
| **Student** | My grades, upcoming lessons, profile |
| **Parent** | Children's grades, psychological assessments |
| **Supervisor** | All teachers, all students, pending approvals |

### 2. Grading System

- **Hierarchical Topics**: Lessons contain topics with subtopics
- **Weighted Grades**: Each topic has a weight (must sum to 100%)
- **Auto-Distribution**: "Distribute equally" feature for topic weights
- **Batch Grading**: Grade all students in a lesson at once
- **Quarter Tracking**: Grades organized by academic quarters (1-4)

### 3. Psychological Wellness Tracking

- 5-star rating system for student mental health
- Reusable templates for common assessments
- Automatic parent notifications
- Historical tracking with timestamps

### 4. Data Import

- Google Sheets integration for bulk imports
- XLS file support for user data
- Import status tracking per record
- Supports: Students, Teachers, Parents, Subjects, Lessons, Grades

### 5. Notifications

| Type | Trigger | Recipients |
|------|---------|------------|
| Registration | New user signup | User |
| Grade Released | Teacher submits grade | Parent |
| Psychological Update | Assessment added | Parent |
| Profile Edit Request | Student requests change | Supervisor |

---

## Setup & Installation

### Prerequisites

- Docker & Docker Compose
- AWS S3 bucket (for media storage)
- Gmail account (for SMTP)
- Google Cloud service account (for Sheets API)

### Environment Variables

Create `.env` file in project root:

```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=qadam
DB_USER=qadam
DB_PASSWORD=your-password
DB_HOST=db
DB_PORT=5432

# AWS S3
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# Email
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# AI Reports
OPENAI_API_KEY=sk-...
AI_REPORT_MODEL=gpt-4o-mini

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Redis (cache)
REDIS_URL=redis://redis:6379/1

# Google Sheets
SPREADSHEET_URL=https://docs.google.com/spreadsheets/d/...
SERVICE_ACCOUNT_FILE=./core/credentials/service_account.json
```

### Requirements Files

| File | Purpose | When to use |
|------|---------|-------------|
| `requirements.txt` | Production dependencies only (Django, DRF, PostgreSQL driver, Redis, etc.) | Docker builds, production deployments |
| `requirements-dev.txt` | Extends `requirements.txt` with testing and linting tools (pytest, factory-boy, ruff, django-debug-toolbar) | Local development, CI pipeline |
| `requirements-scripts.txt` | Extends `requirements.txt` with script-only dependencies (gspread for Google Sheets) | Running bulk import scripts in `scripts/` |

```bash
# Production
pip install -r requirements.txt

# Development & testing
pip install -r requirements-dev.txt

# Running import scripts
pip install -r requirements-scripts.txt
```

### Development Setup

```bash
# Clone repository
git clone https://github.com/Pro100-Almaz/qadam-analytics.git
cd qadam-analytics

# Start development environment
docker-compose -f docker-compose.dev.yml up --build

# Access application
open http://localhost:8000
```

### Production Setup

```bash
# Build and start production containers
docker-compose up --build -d

# View logs
docker-compose logs -f

# Run migrations manually (if needed)
docker-compose exec appseed-app python manage.py migrate
```

---

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/login/` | User login |
| GET/POST | `/register/` | User registration |
| GET | `/logout/` | User logout |
| POST | `/forget_pass_confirm/` | Request password reset |
| GET/POST | `/reset/<uidb64>/<token>/` | Reset password |
| POST | `/validate/<username>/<code>/` | Validate reset code |

### Dashboard & Profile

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main dashboard |
| GET | `/pages/profile/` | View profile |
| POST | `/pages/profile/update/` | Update profile |
| POST | `/pages/profile/edit_request/` | Request profile changes |

### Students

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pages/students/` | List students |
| GET | `/pages/students/<id>/` | Student details |
| POST | `/pages/students/<id>/student_profile_update/` | Update student |
| POST | `/pages/students/<id>/psychological_state_create/` | Add psych state |

### Teachers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pages/teachers/` | List teachers |
| GET | `/pages/teachers/<id>/` | Teacher details |
| POST | `/pages/teacher/<id>/profile_update/` | Update teacher |

### Subjects

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pages/subjects/` | List active subjects |
| GET | `/pages/subjects/archive/` | Archived subjects |
| GET | `/pages/my_subjects/` | Teacher's subjects |
| POST | `/pages/subjects/new/` | Create subject |
| POST | `/pages/subjects/<id>/archive/` | Archive subject |
| POST | `/pages/subjects/<id>/delete/` | Delete subject |

### Lessons & Grading

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lessons/` | List lessons (with filters) |
| GET | `/lessons/<id>/` | Lesson details |
| GET | `/lessons/grading/<id>/` | Grading interface |
| POST | `/lessons/grading/submit/` | Submit grades |
| POST | `/lessons/grading/update/<id>/` | Update single grade |
| POST | `/lessons/create/` | Create lesson |
| POST | `/lessons/topic/create/<pk>/` | Create topic |
| POST | `/lessons/topic/distribute_equally/<pk>/` | Auto-distribute weights |

---

## External Integrations

### AWS S3

- **Bucket**: `qadam-avatars`
- **Region**: `eu-north-1`
- **Usage**: User avatars, school group images
- **Paths**: `avatars/%Y/%m/%d/`, `school_group/`

### Google Sheets

- **Purpose**: Bulk data import
- **Authentication**: Service account JSON
- **Supported imports**: Students, Teachers, Parents, Subjects, Lessons, Grades

### Gmail SMTP

- **Host**: `smtp.gmail.com:587`
- **Usage**: Registration emails, password reset, notifications

---

## AI Student Reports

AI-powered quarterly performance reports for students, generated via OpenAI API and processed asynchronously with Celery.

### How It Works

```
Teacher clicks "Generate Report"
         |
         v
POST /api/v1/students/<id>/reports/generate/
         |
         +--> Check cache (same params within 1 hour?) --> Return cached (200)
         |
         +--> Create StudentReport (status: pending)
         |
         +--> Queue Celery task (generate_report_task)
         |
         +--> Return 202 Accepted (report ID for polling)
                    |
                    v  (async in Celery worker)
            +------------------+
            | Data Collector   |  Gathers: grades, psych states,
            | (data_collector) |  achievements, reading, clubs
            +--------+---------+
                     |
                     v
            +------------------+
            | Prompt Builder   |  Builds system + user prompts
            | (prompt_builder) |  with structured JSON schema
            +--------+---------+
                     |
                     v
            +------------------+
            |  OpenAI API      |  gpt-4o-mini (JSON mode)
            |  (generator)     |  Validates required keys
            +--------+---------+
                     |
                     v
            Report saved (status: completed)
                     |
                     +--> Email notification to teacher
```

### API Endpoints

| Method | Endpoint | Description | Response |
|--------|----------|-------------|----------|
| POST | `/api/v1/students/<id>/reports/generate/` | Queue report generation | 202 (queued) or 200 (cached) |
| GET | `/api/v1/students/<id>/reports/` | List past reports for student | Array (excludes `report_data`) |
| GET | `/api/v1/reports/<id>/` | Get single report with full data | Full report JSON |
| GET | `/api/v1/reports/<id>/pdf/` | Download report as PDF | Binary PDF |

**Generate Request Body:**

```json
{
  "language": "ru",
  "quarter": 3
}
```

- `language`: required — `"ru"` (Russian), `"kk"` (Kazakh), `"en"` (English)
- `quarter`: required — integer 1-4

**Report Response:**

```json
{
  "id": 42,
  "student": 15,
  "academic_year": 3,
  "quarter": 3,
  "language": "ru",
  "status": "pending",
  "report_data": null,
  "tokens_used": null,
  "generation_time_ms": null,
  "generated_by": 7,
  "generated_by_name": "Aisha Nurlanovna",
  "created_at": "2026-05-04T14:30:00Z",
  "error_message": ""
}
```

`status` values: `pending` → `generating` → `completed` / `failed`

When `status == "completed"`, `report_data` contains the structured JSON:

```json
{
  "summary": "2-3 sentence executive summary",
  "overall_assessment": { "score_label": "Good", "description": "..." },
  "academic_performance": {
    "overview": "...",
    "subject_analyses": [
      {
        "subject": "Mathematics",
        "grade_percentage": 85.0,
        "class_average": 72.0,
        "trend": "improving",
        "analysis": "...",
        "recommendation": "..."
      }
    ]
  },
  "strengths": [{ "area": "...", "description": "..." }],
  "areas_for_improvement": [{ "area": "...", "description": "...", "suggested_action": "..." }],
  "psychological_profile": { "summary": "...", "observations": [], "recommendations": [] },
  "extracurricular": { "summary": "...", "highlights": [] },
  "recommendations": { "for_teachers": [], "for_parents": [], "for_student": [] },
  "conclusion": "2-3 sentence closing"
}
```

### Rate Limiting

Report generation is throttled at **10 requests per hour per user**. Duplicate requests (same student + quarter + language) within 1 hour return the cached report.

### Running the Celery Worker

```bash
# Production (via docker-compose, starts automatically)
docker compose up -d

# Development (if running Django locally)
celery -A core worker -l info
```

### PDF Export

Reports can be downloaded as styled A4 PDFs with:
- School header and metadata
- Subject grade table with class average comparison
- Trend indicators (↑ improving, ↓ declining, → stable)
- Strengths and improvement areas as cards
- Psychological profile, extracurricular, and recommendations sections
- Cyrillic/Kazakh font support (Noto Sans)

### Data Sources

The report collects data from across the platform:

| Data | Source Model | What's Included |
|------|-------------|-----------------|
| Grades | `Lesson`, `Topic`, `TopicGrade` | Per-subject, per-quarter averages + cumulative |
| Trends | Computed from grades | Quarter-over-quarter direction (±3% threshold) |
| Class averages | All students in class group | Per-subject average for comparison |
| Psych states | `PsychologicalState` | Current states + recent score changes |
| Achievements | `Achievement` | Category, award type, place, role |
| Reading | `ReadingEntry` | Title, pages read, test score |
| Clubs | `ClubEntry` | Club name, attendance %, plan, criteria |

---

## Development

### Running Tests

```bash
docker-compose -f docker-compose.dev.yml exec appseed-app python manage.py test
```

### Database Migrations

```bash
# Create migrations
docker-compose exec appseed-app python manage.py makemigrations

# Apply migrations
docker-compose exec appseed-app python manage.py migrate
```

### Creating Superuser

```bash
docker-compose exec appseed-app python manage.py createsuperuser
```

### Code Style

```bash
# Check code style
pycodestyle apps/ core/
```

---

## License

Proprietary - Qadam Education Platform

---

## Support

For issues and feature requests, please contact the development team.
