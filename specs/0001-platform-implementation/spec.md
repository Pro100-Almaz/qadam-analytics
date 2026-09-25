---
id: 0001
slug: platform-implementation
title: Platform Implementation — security, tests, refactors, features
status: in-progress
owner: almaz
created: 2026-05-27
updated: 2026-09-21
---

> **Migrated document.** Written before this repo adopted the spec workflow, so
> it is structured as a phased implementation guide rather than the template in
> `specs/templates/spec.md`. Content below is unchanged. New work should be
> split out into its own numbered spec rather than appended here.

# Qadam Analytics — Implementation Spec

**Purpose:** Step-by-step implementation guide for a coding agent.  
**Stack:** Django 5.2 / Python 3.13 / PostgreSQL 14 / DRF 3.15.2  
**Repo structure assumption:** `apps/` contains `authentication`, `home`, `lesson`, `notification`, `achievement`. Settings in `core/settings.py`. URLs in `core/urls.py`.

---

## Phase 1 — Critical Security Fixes

> **Do these first. Do not skip to later phases until Phase 1 is complete.**

### 1.1 Fix Password Reset Flow

**Problem:** `POST /forget-password/` returns the `signed_code` directly in the response body. No out-of-band verification exists — anyone who knows a username can reset that account's password.

**Files to modify:**
- `apps/authentication/api/views.py` — the `ForgetPasswordView` (or equivalent)
- `apps/authentication/api/serializers.py` — the forget-password serializer
- `core/settings.py` — add email backend config

**Implementation steps:**

1. Install `django.core.mail` backend or configure an SMTP/SendGrid/SES backend in `core/settings.py`:
   ```python
   # core/settings.py
   EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
   EMAIL_HOST = env('EMAIL_HOST')
   EMAIL_PORT = env('EMAIL_PORT', default=587)
   EMAIL_USE_TLS = True
   EMAIL_HOST_USER = env('EMAIL_HOST_USER')
   EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
   DEFAULT_FROM_EMAIL = 'noreply@qadamanalytics.kz'
   ```

2. Modify the `ForgetPasswordView`:
   - Generate a 6-digit numeric code and a `signed_code` (keep the signing logic).
   - Store the code in cache or a `PasswordResetCode` model with fields: `user`, `code_hash`, `created_at`, `expires_at` (10-minute TTL), `attempts` (default 0, max 5).
   - Send the 6-digit code to the user's email (or phone via SMS provider).
   - Return ONLY `{"message": "Verification code sent", "username": "<username>"}` — **never return the code or signed_code**.

3. Modify the `VerifyCodeView`:
   - Accept `{"code": "123456"}` in the request body (not URL path).
   - Look up the stored code for that username, compare hashes.
   - Increment `attempts` on each try. If `attempts >= 5`, invalidate the code and return 429.
   - If valid, return a short-lived signed token for the change-password step.

4. Modify the `ChangePasswordView`:
   - Accept `{"token": "<signed_token>", "new_password": "..."}` in the request body.
   - Validate the signed token (check signature + expiry).
   - Change the password, invalidate all existing refresh tokens for that user.
   - Delete the reset code record.

5. Update URL patterns — remove `<str:signed_code>` and `<str:username>` from URL paths:
   ```python
   # BEFORE
   path('verify-code/<str:username>/<str:signed_code>/', VerifyCodeView.as_view()),
   path('change-password/<str:username>/<str:signed_code>/', ChangePasswordView.as_view()),
   
   # AFTER
   path('verify-code/', VerifyCodeView.as_view()),
   path('change-password/', ChangePasswordView.as_view()),
   ```

6. Update API docs and any Swagger schema extensions.

**Acceptance criteria:**
- `POST /forget-password/` response contains no code, no token, no signed value.
- `POST /verify-code/` accepts code in request body, returns 429 after 5 failed attempts.
- `POST /change-password/` accepts token in request body, invalidates all refresh tokens.
- Existing frontend references updated (search for `verify-code` and `change-password` in any client code).

---

### 1.2 Add Rate Limiting on Auth Endpoints

**Problem:** `forget-password/`, `verify-code/`, `change-password/`, and `login/` have `AllowAny` permission with no throttling. Vulnerable to brute force.

**Files to modify:**
- `core/settings.py`
- `apps/authentication/api/views.py`

**Implementation steps:**

1. Add throttle configuration to `REST_FRAMEWORK` in `core/settings.py`:
   ```python
   REST_FRAMEWORK = {
       # ... existing config ...
       'DEFAULT_THROTTLE_CLASSES': [
           'rest_framework.throttling.ScopedRateThrottle',
       ],
       'DEFAULT_THROTTLE_RATES': {
           'login': '5/minute',
           'password_reset': '3/minute',
           'verify_code': '5/minute',
           'default': '100/minute',
       },
   }
   ```

2. Add `throttle_scope` to each auth view:
   ```python
   class LoginView(GenericAPIView):
       permission_classes = [AllowAny]
       throttle_scope = 'login'

   class ForgetPasswordView(GenericAPIView):
       permission_classes = [AllowAny]
       throttle_scope = 'password_reset'

   class VerifyCodeView(GenericAPIView):
       permission_classes = [AllowAny]
       throttle_scope = 'verify_code'

   class ChangePasswordView(GenericAPIView):
       permission_classes = [AllowAny]
       throttle_scope = 'password_reset'
   ```

3. When Redis is configured (Phase 3), switch the throttle cache backend:
   ```python
   REST_FRAMEWORK = {
       'DEFAULT_THROTTLE_CACHE': 'default',  # points to Redis
   }
   ```

**Acceptance criteria:**
- 6th login attempt within 1 minute returns HTTP 429 with `Retry-After` header.
- 4th `forget-password` call within 1 minute returns HTTP 429.
- Throttle state persists across requests (uses Django cache backend).

---

### 1.3 Fix Silent Exception Swallowing in Logout

**Problem:** `except Exception: pass` in `LogoutView` means token blacklisting failures are invisible. User thinks they logged out but their refresh token is still valid.

**File to modify:** `apps/authentication/api/views.py` (around line 70)

**Implementation:**

1. Find the `LogoutView` and replace the bare except:
   ```python
   # BEFORE
   class LogoutView(APIView):
       def post(self, request):
           try:
               refresh_token = request.data.get('refresh')
               token = RefreshToken(refresh_token)
               token.blacklist()
               return Response(status=205)
           except Exception:
               pass  # <-- REMOVE THIS
   
   # AFTER
   class LogoutView(APIView):
       def post(self, request):
           refresh_token = request.data.get('refresh')
           if not refresh_token:
               return Response(
                   {"detail": "Refresh token is required."},
                   status=status.HTTP_400_BAD_REQUEST
               )
           try:
               token = RefreshToken(refresh_token)
               token.blacklist()
           except TokenError:
               # Token is already expired or blacklisted — that's fine,
               # the user is effectively logged out.
               pass
           except Exception:
               import logging
               logger = logging.getLogger(__name__)
               logger.exception("Failed to blacklist refresh token during logout")
               return Response(
                   {"detail": "Logout failed. Please try again."},
                   status=status.HTTP_500_INTERNAL_SERVER_ERROR
               )
           return Response(status=status.HTTP_205_RESET_CONTENT)
   ```

**Acceptance criteria:**
- Missing refresh token returns 400.
- Expired/already-blacklisted token returns 205 (success — effectively logged out).
- Unexpected errors return 500 and are logged.

---

### 1.4 Lock Down CORS and ALLOWED_HOSTS

**File to modify:** `core/settings.py`

**Implementation:**

```python
# BEFORE
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
    ALLOWED_HOSTS = ['*']

# AFTER
if DEBUG:
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://localhost:5173',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:5173',
    ]
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']
else:
    CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')
    ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
```

Add `CORS_ALLOWED_ORIGINS` and `ALLOWED_HOSTS` to `.env.example` with sample values.

---

### 1.5 Restrict AllowAny on school-groups

**File to modify:** `apps/authentication/api/views.py` and `apps/authentication/api/urls.py`

**Implementation:**
- If `school-groups/` is used during registration, keep `AllowAny` but strip the response to only return `id` and `name` — no internal metadata, no student counts, no teacher references.
- If it's used post-login, change permission to `IsAuthenticated`.
- Add a serializer that explicitly whitelists returned fields:
  ```python
  class PublicSchoolGroupSerializer(serializers.ModelSerializer):
      class Meta:
          model = SchoolGroup
          fields = ['id', 'name']
  ```

---

## Phase 2 — Test Suite & CI

> **Write tests before any further refactoring. Tests are the safety net for everything in Phases 3-6.**

### 2.1 Test Infrastructure Setup

**Files to create:**
- `conftest.py` (project root)
- `pytest.ini` or add `[tool.pytest.ini_options]` to `pyproject.toml`
- `factories.py` per app (or a shared `core/factories.py`)

**Implementation steps:**

1. Install test dependencies:
   ```
   pip install pytest pytest-django factory-boy faker
   ```
   Add to `requirements-dev.txt` (create this file, see 2.1.3).

2. Create `pytest.ini` at project root:
   ```ini
   [pytest]
   DJANGO_SETTINGS_MODULE = core.settings
   python_files = tests.py test_*.py *_tests.py
   python_classes = Test*
   python_functions = test_*
   addopts = -v --tb=short --strict-markers
   markers =
       slow: marks tests as slow (deselect with '-m "not slow"')
       integration: marks integration tests
   ```

3. Split requirements:
   ```
   # requirements.txt — production only
   # (remove autopep8, pycodestyle, any dev tools)

   # requirements-dev.txt
   -r requirements.txt
   pytest==8.*
   pytest-django==4.*
   factory-boy==3.*
   faker==37.*
   autopep8
   pycodestyle
   django-debug-toolbar
   ```

4. Create `core/factories.py` with base factories:
   ```python
   import factory
   from factory.django import DjangoModelFactory
   from django.contrib.auth import get_user_model
   # Import your models

   User = get_user_model()

   class UserFactory(DjangoModelFactory):
       class Meta:
           model = User
       username = factory.Sequence(lambda n: f'user_{n}')
       email = factory.LazyAttribute(lambda o: f'{o.username}@test.kz')
       password = factory.PostGenerationMethodCall('set_password', 'testpass123')
       role = 'student'  # default, override per test

   class SchoolGroupFactory(DjangoModelFactory):
       class Meta:
           model = 'authentication.SchoolGroup'  # adjust to actual model path
       name = factory.Sequence(lambda n: f'School {n}')

   class AcademicYearFactory(DjangoModelFactory):
       class Meta:
           model = 'home.AcademicYear'  # adjust
       name = factory.Sequence(lambda n: f'202{n}-202{n+1}')
       is_current = True

   class StudentFactory(DjangoModelFactory):
       class Meta:
           model = 'home.Student'  # adjust
       user = factory.SubFactory(UserFactory, role='student')
       school_group = factory.SubFactory(SchoolGroupFactory)
       academic_year = factory.SubFactory(AcademicYearFactory)

   class TeacherFactory(DjangoModelFactory):
       class Meta:
           model = 'home.Teacher'  # adjust
       user = factory.SubFactory(UserFactory, role='teacher')

   class ParentFactory(DjangoModelFactory):
       class Meta:
           model = 'home.Parent'  # adjust
       user = factory.SubFactory(UserFactory, role='parent')

   class SubjectOfferingFactory(DjangoModelFactory):
       # ... define based on your SubjectOffering model

   class LessonFactory(DjangoModelFactory):
       # ... define based on your Lesson model

   class TopicFactory(DjangoModelFactory):
       # ... define based on your Topic model

   class TopicGradeFactory(DjangoModelFactory):
       # ... define based on your TopicGrade model
   ```

5. Create `conftest.py` at project root with shared fixtures:
   ```python
   import pytest
   from rest_framework.test import APIClient
   from core.factories import (
       UserFactory, StudentFactory, TeacherFactory, ParentFactory,
       AcademicYearFactory, SchoolGroupFactory
   )

   @pytest.fixture
   def api_client():
       return APIClient()

   @pytest.fixture
   def admin_user(db):
       user = UserFactory(role='admin', is_staff=True)
       return user

   @pytest.fixture
   def teacher_user(db):
       teacher = TeacherFactory()
       return teacher

   @pytest.fixture
   def student_user(db):
       student = StudentFactory()
       return student

   @pytest.fixture
   def parent_user(db):
       parent = ParentFactory()
       return parent

   @pytest.fixture
   def authenticated_client(api_client):
       """Returns a function that authenticates the client as a given user."""
       def _auth(user):
           api_client.force_authenticate(user=user)
           return api_client
       return _auth

   @pytest.fixture
   def academic_year(db):
       return AcademicYearFactory(is_current=True)
   ```

---

### 2.2 Permission Tests

**File to create:** `apps/authentication/tests/test_permissions.py` (and similar per app)

**Test matrix — each row is a test case:**

```python
import pytest
from django.urls import reverse
from rest_framework import status

# ─── Vertical privilege tests (role cannot access higher-role endpoints) ───

class TestStudentPermissionBoundaries:
    """Students must not access teacher/admin endpoints."""

    @pytest.mark.parametrize("url_name,method", [
        ("subject-create", "post"),      # POST /subjects/new/
        ("student-update", "patch"),      # PATCH /students/<pk>/update/
        ("teacher-update", "patch"),      # PATCH /teachers/<pk>/update/
        ("lesson-create", "post"),        # POST /lessons/
        ("enrollment-list", "get"),       # GET /enrollments/
        ("register", "post"),            # POST /auth/register/
    ])
    def test_student_cannot_access_admin_endpoints(
        self, authenticated_client, student_user, url_name, method
    ):
        client = authenticated_client(student_user.user)
        url = reverse(url_name, kwargs={"pk": 1}) if "pk" in url_name else reverse(url_name)
        response = getattr(client, method)(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

class TestParentPermissionBoundaries:
    """Parents must not access teacher/admin endpoints."""

    @pytest.mark.parametrize("url_name,method", [
        ("lesson-create", "post"),
        ("subject-create", "post"),
        ("grading-create", "post"),
    ])
    def test_parent_cannot_access_teacher_endpoints(
        self, authenticated_client, parent_user, url_name, method
    ):
        client = authenticated_client(parent_user.user)
        url = reverse(url_name)
        response = getattr(client, method)(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

# ─── Horizontal privilege tests (user cannot access other user's data) ───

class TestHorizontalAccessControl:

    def test_parent_cannot_see_other_parents_children(
        self, authenticated_client, parent_user, db
    ):
        """Parent A must not see Parent B's children."""
        from core.factories import ParentFactory, StudentFactory
        other_parent = ParentFactory()
        other_child = StudentFactory()
        other_parent.children.add(other_child)

        client = authenticated_client(parent_user.user)
        url = reverse("parent-child-detail", kwargs={"pk": other_child.pk})
        response = client.get(url)
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND
        ]

    def test_teacher_cannot_grade_other_teachers_offering(
        self, authenticated_client, teacher_user, db
    ):
        """Teacher A must not submit grades for Teacher B's lesson."""
        from core.factories import TeacherFactory, LessonFactory
        other_teacher = TeacherFactory()
        other_lesson = LessonFactory()  # assigned to other_teacher's offering

        client = authenticated_client(teacher_user.user)
        url = reverse("lesson-grading", kwargs={"id": other_lesson.pk})
        response = client.post(url, data={"grades": []}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_cannot_see_other_students_detail(
        self, authenticated_client, student_user, db
    ):
        """Student A must not access Student B's detail endpoint."""
        from core.factories import StudentFactory
        other_student = StudentFactory()

        client = authenticated_client(student_user.user)
        url = reverse("student-detail", kwargs={"pk": other_student.pk})
        response = client.get(url)
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND
        ]
```

**Note to agent:** Adjust `reverse()` names to match actual URL names in `urls.py`. If URL names differ, grep the codebase for `name=` in URL patterns and use those.

---

### 2.3 Grade Calculation Tests

**File to create:** `apps/lesson/tests/test_grade_calculation.py`

```python
import pytest
from decimal import Decimal

# Adjust imports to match your actual model/method locations
# from apps.lesson.models import Lesson, Topic, TopicGrade
# from apps.lesson.api.views import (or services if extracted)

class TestGradeCalculation:
    """Tests for Lesson.calculate_grades_bulk() and related methods."""

    @pytest.fixture
    def grading_setup(self, db):
        """
        Create a complete grading scenario:
        - 1 SubjectOffering with 1 Lesson
        - Lesson has 3 Topics with weights [40, 30, 30]
        - 3 Students enrolled
        """
        # Build the full object graph using factories
        # Return a dict with all objects for easy access
        # {offering, lesson, topics: [t1, t2, t3], students: [s1, s2, s3]}
        pass  # Agent: implement using the factories from 2.1

    def test_perfect_scores_equal_max_grade(self, grading_setup):
        """Student with max score on all topics gets 100%."""
        # Create TopicGrade with max score for each topic
        # Call calculate_grades_bulk
        # Assert student grade == 100 (or max in your scale)
        pass

    def test_zero_scores_equal_zero(self, grading_setup):
        """Student with 0 on all topics gets 0%."""
        pass

    def test_weighted_average_is_correct(self, grading_setup):
        """
        Topics weighted [40, 30, 30]. Student scores [10, 5, 8] out of 10.
        Expected: (10*40 + 5*30 + 8*30) / (10*40 + 10*30 + 10*30)
               = (400 + 150 + 240) / 1000
               = 79%
        """
        pass

    def test_missing_grades_treated_as_absent(self, grading_setup):
        """
        Student has grades for 2 of 3 topics.
        Verify: missing topic is treated as 0 (not excluded from average).
        """
        pass

    def test_bulk_calculation_matches_individual(self, grading_setup):
        """
        calculate_grades_bulk() for N students must produce same results
        as calculating individually for each student.
        """
        pass

    def test_no_n_plus_one_queries(self, grading_setup, django_assert_num_queries):
        """
        Bulk grade calculation for 30 students should use a bounded
        number of queries (not proportional to student count).
        """
        # with django_assert_num_queries(num) where num is a reasonable bound
        pass

    def test_subtopic_grades_roll_up_to_parent_topic(self, grading_setup):
        """If topics have subtopics, subtopic grades should aggregate into parent."""
        pass

    def test_graded_percent_map_accuracy(self, grading_setup):
        """_build_graded_percent_map() returns correct completion % per lesson."""
        pass

class TestQuarterGrades:
    """Tests for quarter-level grade aggregation."""

    def test_quarter_grade_aggregates_all_lessons_in_quarter(self, db):
        """Quarter grade = weighted average across all lessons in that quarter."""
        pass

    def test_different_quarters_are_independent(self, db):
        """Changing Q1 grades must not affect Q2 grade calculation."""
        pass
```

**Note to agent:** The `pass` stubs must be replaced with actual assertions once the exact model field names and method signatures are confirmed from the codebase. Read `apps/lesson/models.py` and `apps/lesson/api/views.py` first.

---

### 2.4 Auth Flow Tests

**File to create:** `apps/authentication/tests/test_auth_flow.py`

```python
import pytest
from django.urls import reverse
from rest_framework import status

class TestLoginFlow:

    def test_valid_login_returns_tokens(self, api_client, db):
        from core.factories import UserFactory
        user = UserFactory(role='teacher')
        response = api_client.post(reverse('login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' in response.data

    def test_wrong_password_returns_401(self, api_client, db):
        from core.factories import UserFactory
        user = UserFactory()
        response = api_client.post(reverse('login'), {
            'username': user.username,
            'password': 'wrongpassword',
        })
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_nonexistent_user_returns_401(self, api_client, db):
        response = api_client.post(reverse('login'), {
            'username': 'ghost',
            'password': 'whatever',
        })
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_404_NOT_FOUND
        ]

    def test_login_throttle_after_5_attempts(self, api_client, db):
        for _ in range(6):
            response = api_client.post(reverse('login'), {
                'username': 'ghost',
                'password': 'wrong',
            })
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

class TestTokenRefresh:

    def test_valid_refresh_returns_new_access(self, api_client, db):
        from core.factories import UserFactory
        user = UserFactory()
        login = api_client.post(reverse('login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        response = api_client.post(reverse('token_refresh'), {
            'refresh': login.data['refresh'],
        })
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data

    def test_blacklisted_refresh_token_rejected(self, api_client, db):
        from core.factories import UserFactory
        user = UserFactory()
        login = api_client.post(reverse('login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        refresh = login.data['refresh']
        # Logout (blacklists the token)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        api_client.post(reverse('logout'), {'refresh': refresh})
        # Try to use the blacklisted refresh token
        api_client.credentials()
        response = api_client.post(reverse('token_refresh'), {'refresh': refresh})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

class TestLogout:

    def test_logout_blacklists_refresh_token(self, authenticated_client, db):
        from core.factories import UserFactory
        user = UserFactory()
        client = authenticated_client(user)
        # Get a refresh token first
        client_unauth = __import__('rest_framework.test', fromlist=['APIClient']).APIClient()
        login = client_unauth.post(reverse('login'), {
            'username': user.username,
            'password': 'testpass123',
        })
        refresh = login.data['refresh']
        response = client.post(reverse('logout'), {'refresh': refresh})
        assert response.status_code == status.HTTP_205_RESET_CONTENT

    def test_logout_without_refresh_returns_400(self, authenticated_client, db):
        from core.factories import UserFactory
        user = UserFactory()
        client = authenticated_client(user)
        response = client.post(reverse('logout'), {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
```

---

### 2.5 GitHub Actions CI

**File to create:** `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: '3.13'
  DJANGO_SETTINGS_MODULE: core.settings

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_USER: qadam_test
          POSTGRES_PASSWORD: qadam_test
          POSTGRES_DB: qadam_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Run linting
        run: |
          pip install ruff
          ruff check .

      - name: Check migrations
        env:
          DATABASE_URL: postgres://qadam_test:qadam_test@localhost:5432/qadam_test
          SECRET_KEY: ci-test-secret-key-not-for-production
        run: |
          python manage.py makemigrations --check --dry-run

      - name: Run tests
        env:
          DATABASE_URL: postgres://qadam_test:qadam_test@localhost:5432/qadam_test
          SECRET_KEY: ci-test-secret-key-not-for-production
        run: |
          pytest --tb=short -q

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Check for known vulnerabilities
        run: |
          pip install pip-audit
          pip-audit
```

**Note to agent:** The `DATABASE_URL` env var must be read in `core/settings.py`. If the project uses `django-environ` or `dj-database-url`, it should already work. If not, add `dj-database-url` and wire it:
```python
import dj_database_url
DATABASES = {
    'default': dj_database_url.config(default='postgres://localhost:5432/qadam')
}
```

---

## Phase 3 — Structural Refactors

### 3.1 Consolidate Duplicate Permission Classes

**Problem:** `IsTeacherAdminOrSupervisor` is copy-pasted in 3 files.

**Files to modify:**
- Create: `core/permissions.py`
- Modify: `apps/home/api/permissions.py`, `apps/lesson/api/permissions.py`, `apps/achievement/api/permissions.py`
- Modify: all views that import from app-level permissions

**Implementation:**

1. Create `core/permissions.py`:
   ```python
   from rest_framework.permissions import BasePermission

   class IsTeacherAdminOrSupervisor(BasePermission):
       """
       Allows access to users with role: teacher, admin, or supervisor.
       """
       def has_permission(self, request, view):
           if not request.user or not request.user.is_authenticated:
               return False
           return request.user.role in ('teacher', 'admin', 'supervisor')

   class IsStudent(BasePermission):
       def has_permission(self, request, view):
           return (
               request.user
               and request.user.is_authenticated
               and request.user.role == 'student'
           )

   class IsParent(BasePermission):
       def has_permission(self, request, view):
           return (
               request.user
               and request.user.is_authenticated
               and request.user.role == 'parent'
           )

   # Add all shared permission classes here
   ```

2. In each app's `permissions.py`, replace the class with an import:
   ```python
   # apps/home/api/permissions.py
   from core.permissions import IsTeacherAdminOrSupervisor  # noqa: F401
   # Keep this re-export for backwards compatibility, but add a deprecation comment.
   # Any app-specific permission classes stay in this file.
   ```

3. Run `grep -rn "from apps.*.api.permissions import" .` to find all import sites. Update to import from `core.permissions`.

4. Run the test suite to verify nothing broke.

---

### 3.2 Extract Service Layer

**Goal:** Move business logic out of views into testable service functions.

**Files to create:**
- `apps/lesson/services.py`
- `apps/home/services.py`
- `apps/achievement/services.py`

**Example — extract grade calculation:**

```python
# apps/lesson/services.py

from typing import Dict, List, Optional
from decimal import Decimal

def calculate_lesson_grades_bulk(
    lesson,
    student_ids: Optional[List[int]] = None,
) -> Dict[int, Decimal]:
    """
    Calculate grades for all (or specified) students in a lesson.
    
    Returns: {student_id: grade_percentage}
    
    This is extracted from Lesson.calculate_grades_bulk().
    The model method should delegate to this function.
    """
    # Move the body of Lesson.calculate_grades_bulk() here
    # Keep the model method as a thin wrapper:
    #   def calculate_grades_bulk(self, student_ids=None):
    #       from apps.lesson.services import calculate_lesson_grades_bulk
    #       return calculate_lesson_grades_bulk(self, student_ids)
    pass

def calculate_quarter_grade(
    student_id: int,
    offering_id: int,
    quarter: int,
) -> Optional[Decimal]:
    """
    Calculate a student's grade for a specific quarter in a specific offering.
    Returns None if no graded lessons exist.
    """
    pass

def build_graded_percent_map(
    offering_id: int,
    quarter: Optional[int] = None,
) -> Dict[int, float]:
    """
    Returns {lesson_id: grading_completion_percentage} for all lessons
    in an offering (optionally filtered by quarter).
    """
    pass

def compute_child_grades_batch(
    student_ids: List[int],
    academic_year_id: int,
) -> Dict[int, Dict]:
    """
    Batch compute grades for multiple students (e.g., all children of a parent).
    Avoids N+1 from calling per-child in a loop.
    
    Returns: {student_id: {offering_id: {quarter: grade}}}
    """
    pass
```

**Example — extract enrollment logic:**

```python
# apps/home/services.py

def get_students_for_role(user, filters=None):
    """
    Returns filtered student queryset based on user role.
    Admin: all students (with optional filters)
    Teacher: students in teacher's offerings
    Parent: own children
    Student: self only
    """
    pass

def get_dashboard_stats(user) -> dict:
    """
    Returns dashboard statistics based on user role.
    Extracted from DashboardStatsView.
    """
    pass
```

**Migration strategy:**
1. Create the service function.
2. Move the logic from the view/model into the service.
3. Make the view call the service.
4. Make the model method (if any) call the service.
5. Write a test for the service directly (no HTTP needed).
6. Verify the existing API behavior hasn't changed.

---

### 3.3 Split home/api/views.py (~850 lines)

**Current structure:**
```
apps/home/api/views.py  (850 lines, 20+ views)
```

**Target structure:**
```
apps/home/api/
    views/
        __init__.py          # re-exports all views for backwards compat
        students.py          # StudentListView, StudentDetailView, StudentUpdateView,
                             # StudentMeSubjectsView, StudentMeTeachersView,
                             # StudentMeClassmatesView
        teachers.py          # TeacherListView, TeacherDetailView, TeacherUpdateView
        parents.py           # ParentTeachersView, ParentMeChildrenView,
                             # ParentMeChildDetailView, ParentMeTeachersView
        subjects.py          # SubjectListView, SubjectCreateView, SubjectDetailView,
                             # SubjectGradesView, SubjectStatusView, SubjectDeleteView,
                             # MySubjectsView
        enrollments.py       # EnrollmentListView
        dashboard.py         # DashboardStatsView
        psychological.py     # PsychologicalStateCreateView, PsychologicalStateDeleteView,
                             # PsychologicalStateTemplateListView
        academic.py          # AcademicYearListView, ClassGroupListView
    services.py              # Business logic (from 3.2)
    serializers/
        __init__.py
        students.py
        teachers.py
        # ... mirror the views split
```

**Implementation steps:**

1. Create the `views/` directory and `__init__.py`.
2. Move views one file at a time. After each move, run tests.
3. The `__init__.py` must re-export everything:
   ```python
   # apps/home/api/views/__init__.py
   from .students import *
   from .teachers import *
   from .parents import *
   from .subjects import *
   from .enrollments import *
   from .dashboard import *
   from .psychological import *
   from .academic import *
   ```
4. URL files should not need changes if imports resolve through `__init__.py`.
5. Also split `lesson/api/views.py` (~700 lines) using the same pattern.

---

### 3.4 Unify Notification Models

**Problem:** 4 separate models (`RegisterNotify`, `LoginNotify`, `GradingNotify`, `PsychologicalNotify`) with 1:1 links to `Notification`.

**Target:** Single `Notification` model with a `type` field and JSON metadata.

**File to modify:** `apps/notification/models.py`

**New model:**

```python
from django.db import models
from django.conf import settings

class Notification(models.Model):
    class NotificationType(models.TextChoices):
        REGISTER = 'register', 'Registration'
        LOGIN = 'login', 'Login'
        GRADING = 'grading', 'Grading'
        PSYCHOLOGICAL = 'psychological', 'Psychological State'
        # Future types can be added without migrations:
        # ATTENDANCE = 'attendance', 'Attendance'
        # HOMEWORK = 'homework', 'Homework'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Type-specific data. Examples: "
                  "grading: {lesson_id, parent_id, grade}; "
                  "psychological: {parent_id, psychologist_id}"
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]
```

**Data migration:** Write a data migration that moves existing rows from the 4 child tables into the new unified `Notification` format, mapping each child model's fields into `metadata`. Then remove the old models in a subsequent migration.

---

### 3.5 Standardize Error Messages

**Problem:** Mixed Russian and English error messages.

**Implementation:** Use Django's i18n framework.

1. Create message constants:
   ```python
   # core/error_messages.py
   from django.utils.translation import gettext_lazy as _

   # Auth errors
   USER_NOT_FOUND = _("User not found.")
   INVALID_PASSWORD = _("Invalid password.")
   PASSWORD_MISMATCH = _("Passwords do not match.")
   TOKEN_EXPIRED = _("Token has expired.")
   ACCOUNT_DISABLED = _("This account has been disabled.")

   # Permission errors
   NO_PERMISSION = _("You do not have permission to perform this action.")
   OBJECT_NOT_FOUND = _("The requested resource was not found.")

   # Validation errors
   REQUIRED_FIELD = _("This field is required.")
   INVALID_FORMAT = _("Invalid format.")
   ```

2. Create locale files:
   ```
   locale/
       ru/
           LC_MESSAGES/
               django.po
       kk/
           LC_MESSAGES/
               django.po
   ```

3. Replace all hardcoded strings in views and serializers with imports from `core/error_messages.py`.

4. Add to `core/settings.py`:
   ```python
   LANGUAGE_CODE = 'en'
   LANGUAGES = [
       ('en', 'English'),
       ('ru', 'Russian'),
       ('kk', 'Kazakh'),
   ]
   USE_I18N = True
   LOCALE_PATHS = [BASE_DIR / 'locale']

   MIDDLEWARE = [
       # ... existing ...
       'django.middleware.locale.LocaleMiddleware',  # after SessionMiddleware
   ]
   ```

5. Frontend sends `Accept-Language: ru` header; Django returns messages in that language.

---

## Phase 4 — Database & Performance

### 4.1 Add Composite Indexes

**File to modify:** Each app's `models.py`

**Add these indexes (create a single migration per app):**

```python
# apps/lesson/models.py — Lesson model
class Meta:
    indexes = [
        models.Index(fields=['offering', 'quarter'], name='idx_lesson_offering_qtr'),
        models.Index(fields=['date'], name='idx_lesson_date'),
        models.Index(fields=['offering', 'date'], name='idx_lesson_offering_date'),
    ]

# apps/lesson/models.py — TopicGrade model
class Meta:
    indexes = [
        models.Index(fields=['student', 'topic'], name='idx_topicgrade_student_topic'),
    ]

# apps/home/models.py — Enrollment model
class Meta:
    indexes = [
        models.Index(fields=['academic_year', 'status'], name='idx_enrollment_year_status'),
        models.Index(fields=['student', 'status'], name='idx_enrollment_student_status'),
    ]

# apps/notification/models.py — Notification model (after unification)
class Meta:
    indexes = [
        models.Index(fields=['user', '-created_at'], name='idx_notif_user_created'),
        models.Index(fields=['user', 'is_read'], name='idx_notif_user_read'),
    ]
```

Run `python manage.py makemigrations` and `python manage.py migrate`.

---

### 4.2 Fix SubjectGradesAPIView Performance

**Problem:** O(offerings × enrollments × lessons) complexity.

**File to modify:** `apps/home/api/views.py` (or the new `views/subjects.py` after split)

**Approach — replace Python loops with annotated querysets:**

```python
# apps/home/services.py (or apps/lesson/services.py)

from django.db.models import Avg, Q, Subquery, OuterRef, FloatField
from django.db.models.functions import Coalesce

def get_subject_grades(offering_id: int, quarter: int = None):
    """
    Returns grade data for all students in an offering, computed in SQL.
    """
    from apps.lesson.models import Lesson, TopicGrade
    from apps.home.models import Enrollment

    # Base: all active enrollments for this offering's class group
    enrollments = Enrollment.objects.filter(
        class_group__offerings__id=offering_id,
        status='active',
    ).select_related('student__user')

    # Subquery: average grade per student across all lessons in offering
    lesson_filter = Q(topic__lesson__offering_id=offering_id)
    if quarter:
        lesson_filter &= Q(topic__lesson__quarter=quarter)

    grade_subquery = TopicGrade.objects.filter(
        lesson_filter,
        student=OuterRef('student'),
    ).values('student').annotate(
        avg_grade=Avg('score')  # adjust field name to match your model
    ).values('avg_grade')[:1]

    enrollments = enrollments.annotate(
        calculated_grade=Coalesce(
            Subquery(grade_subquery, output_field=FloatField()),
            0.0
        )
    )

    return enrollments
```

**Note to agent:** The exact subquery structure depends on how grades are stored (per-topic with weights, or flat scores). Read `TopicGrade` model fields and adapt.

---

### 4.3 Add Redis Caching for Grade Calculations

**Files to modify:**
- `core/settings.py`
- `requirements.txt` — add `django-redis`
- `apps/lesson/services.py` (or wherever grade calculation lives)

**Implementation:**

1. Add to `requirements.txt`:
   ```
   django-redis==5.*
   ```

2. Configure cache in `core/settings.py`:
   ```python
   CACHES = {
       'default': {
           'BACKEND': 'django_redis.cache.RedisCache',
           'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379/1'),
           'OPTIONS': {
               'CLIENT_CLASS': 'django_redis.client.DefaultClient',
           },
           'TIMEOUT': 300,  # 5 minutes default
       }
   }
   ```

3. Add caching to grade calculation:
   ```python
   # apps/lesson/services.py
   from django.core.cache import cache

   GRADE_CACHE_TTL = 300  # 5 minutes

   def calculate_lesson_grades_bulk(lesson, student_ids=None):
       cache_key = f"grades:lesson:{lesson.pk}"
       if student_ids:
           cache_key += f":students:{hash(tuple(sorted(student_ids)))}"

       cached = cache.get(cache_key)
       if cached is not None:
           return cached

       # ... actual calculation ...
       result = _do_grade_calculation(lesson, student_ids)
       cache.set(cache_key, result, GRADE_CACHE_TTL)
       return result
   ```

4. Invalidate cache when grades change:
   ```python
   # apps/lesson/services.py
   def invalidate_lesson_grade_cache(lesson_id: int):
       """Call this whenever grades for a lesson are created/updated/deleted."""
       # Delete all cache keys for this lesson
       cache.delete_pattern(f"grades:lesson:{lesson_id}:*")
       cache.delete(f"grades:lesson:{lesson_id}")

   # Wire this into the grading views:
   # In GradingView.post(), GradingView.patch(), GradingView.delete():
   #     invalidate_lesson_grade_cache(lesson.pk)
   ```

5. Add Redis service to `docker-compose.yml`:
   ```yaml
   services:
     redis:
       image: redis:7-alpine
       ports:
         - "6379:6379"
       volumes:
         - redis_data:/data
   volumes:
     redis_data:
   ```

---

### 4.4 Add Pagination to Unbounded Endpoints

**File to modify:** `core/settings.py` and specific views

1. Set a global default pagination:
   ```python
   # core/settings.py
   REST_FRAMEWORK = {
       # ... existing ...
       'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
       'PAGE_SIZE': 50,
   }
   ```

2. For endpoints that need different sizes or should remain unpaginated:
   ```python
   # View that needs custom page size
   class LessonListView(ListAPIView):
       pagination_class = None  # keep unpaginated (small result sets)
       # OR
       class CustomPagination(PageNumberPagination):
           page_size = 100
           page_size_query_param = 'page_size'
           max_page_size = 200
       pagination_class = CustomPagination
   ```

3. Endpoints to add pagination to immediately:
   - `GET /lessons/` — add pagination (default 50)
   - `GET /subjects/<pk>/grades/` — add pagination (default 50)
   - `GET /students/` — add pagination (default 50)
   - `GET /calendar/lessons/` — keep unpaginated but enforce max date range (30 days)

---

## Phase 5 — New Features

### 5.1 Quarter Grade Snapshots

**Goal:** Freeze grades at quarter-end for immutable transcripts.

**File to create:** `apps/lesson/models.py` (add model)

```python
class QuarterGradeSnapshot(models.Model):
    """
    Immutable grade record frozen at quarter close.
    Once created, these are never updated — they serve as official records.
    """
    student = models.ForeignKey('home.Student', on_delete=models.PROTECT)
    offering = models.ForeignKey('home.SubjectOffering', on_delete=models.PROTECT)
    quarter = models.PositiveSmallIntegerField()
    academic_year = models.ForeignKey('home.AcademicYear', on_delete=models.PROTECT)
    final_grade = models.DecimalField(max_digits=5, decimal_places=2)
    max_possible = models.DecimalField(max_digits=5, decimal_places=2)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    letter_grade = models.CharField(max_length=2, blank=True)
    lesson_count = models.PositiveIntegerField()
    graded_lesson_count = models.PositiveIntegerField()
    frozen_at = models.DateTimeField(auto_now_add=True)
    frozen_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        help_text="Admin/supervisor who triggered the freeze"
    )

    class Meta:
        unique_together = ['student', 'offering', 'quarter', 'academic_year']
        indexes = [
            models.Index(fields=['student', 'academic_year']),
            models.Index(fields=['offering', 'quarter']),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("QuarterGradeSnapshot cannot be updated after creation.")
        super().save(*args, **kwargs)
```

**Endpoints to add:**
```
POST /api/v1/offerings/<pk>/freeze-quarter/    (Admin/Supervisor only)
GET  /api/v1/students/<pk>/grade-history/       (Role-based access)
```

**Freeze service:**
```python
# apps/lesson/services.py

def freeze_quarter_grades(offering_id: int, quarter: int, frozen_by_user):
    """
    Snapshot current grades for all enrolled students.
    Raises if already frozen.
    """
    # 1. Check if snapshot already exists (raise if so)
    # 2. Get all enrolled students
    # 3. Calculate current grades for each
    # 4. Bulk create QuarterGradeSnapshot rows
    # 5. Return count of frozen records
    pass
```

---

### 5.2 Audit Logging

**Goal:** Track who changed grades, deleted records.

**Implementation using `django-simple-history`:**

1. Install: `pip install django-simple-history`

2. Add to `INSTALLED_APPS`:
   ```python
   INSTALLED_APPS = [
       # ...
       'simple_history',
   ]
   MIDDLEWARE = [
       # ...
       'simple_history.middleware.HistoryRequestMiddleware',
   ]
   ```

3. Add history tracking to critical models:
   ```python
   # apps/lesson/models.py
   from simple_history.models import HistoricalRecords

   class TopicGrade(models.Model):
       # ... existing fields ...
       history = HistoricalRecords()

   class Lesson(models.Model):
       # ... existing fields ...
       history = HistoricalRecords()

   class Topic(models.Model):
       # ... existing fields ...
       history = HistoricalRecords()

   # apps/home/models.py
   class Enrollment(models.Model):
       # ... existing fields ...
       history = HistoricalRecords()

   class Student(models.Model):
       # ... existing fields ...
       history = HistoricalRecords()
   ```

4. Run `python manage.py makemigrations` and `python manage.py migrate`.

5. Add an admin-only audit endpoint:
   ```
   GET /api/v1/audit/grades/?student=<id>&date_from=<date>&date_to=<date>
   ```

---

### 5.3 Soft Delete

**File to create:** `core/models.py` (base mixin)

```python
from django.db import models
from django.utils import timezone

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        return super().get_queryset()

    def deleted_only(self):
        return super().get_queryset().filter(is_deleted=True)

class SoftDeleteMixin(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'authentication.CustomUser',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
```

**Apply to these models:**
- `Lesson`
- `Topic` / `SubTopic`
- `TopicGrade`
- `Achievement`
- `ReadingEntry`
- `ClubEntry`

**Update delete views** to call `.soft_delete(request.user)` instead of `.delete()`.

**Add admin restore endpoint:**
```
POST /api/v1/admin/restore/<model>/<pk>/   (Admin only)
```

---

### 5.4 Academic Year Transition Workflow

**File to create:** `apps/home/management/commands/rollover_academic_year.py`

```python
from django.core.management.base import BaseCommand
from django.db import transaction

class Command(BaseCommand):
    help = 'Roll over to a new academic year: create year, promote students, archive enrollments.'

    def add_arguments(self, parser):
        parser.add_argument('new_year_name', type=str, help='e.g., 2026-2027')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        new_year_name = options['new_year_name']

        # Step 1: Create new AcademicYear
        # Step 2: Mark current year as not current
        # Step 3: Create ClassGroups for new year (copy structure from current)
        # Step 4: Promote students:
        #   - Increment grade level (e.g., 5A -> 6A)
        #   - Create new Enrollment for each active student
        #   - Mark old enrollments as 'graduated' or 'promoted'
        # Step 5: Clear subject offerings (teachers re-assigned manually)
        # Step 6: Summary output

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes saved"))
            raise transaction.IntegrityError("Dry run rollback")

        self.stdout.write(self.style.SUCCESS(f"Rolled over to {new_year_name}"))
```

**Also expose as admin API endpoint:**
```
POST /api/v1/admin/rollover-year/    (Admin only, requires confirmation flag)
```

---

### 5.5 Teacher Workload Dashboard

**File to create:** `apps/home/api/views/dashboard.py` (add to existing dashboard)

**Endpoint:** `GET /api/v1/dashboard/teacher-workload/` (Teacher/Admin/Supervisor)

**Response structure:**
```json
{
    "teacher_id": 42,
    "period": "current_week",
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

**Service function:**
```python
# apps/home/services.py

def get_teacher_workload(teacher, week_start=None, week_end=None):
    """
    Compute teacher workload stats for the given week.
    Defaults to current week if no dates provided.
    """
    # 1. Get all offerings for teacher
    # 2. Count lessons by date range
    # 3. Compute grading completion using _build_graded_percent_map
    # 4. Find lessons missing topics
    # 5. Return structured dict
    pass
```

---

## Phase 6 — Dependency Cleanup

### 6.1 Remove/Replace Deprecated Packages

| Action | Package | Replacement |
|--------|---------|-------------|
| Remove | `dotenv==0.9.9` | `python-dotenv` (or `django-environ` if already used) |
| Remove | `pytz==2021.1` | `zoneinfo` (stdlib, Python 3.9+) |
| Remove | `Unipath==1.1` | `pathlib` (stdlib) |
| Pin | `gspread` | Pin to specific version, move to `requirements-scripts.txt` if not runtime |
| Move | `autopep8`, `pycodestyle` | Move to `requirements-dev.txt` |
| Add | — | `django-health-check` for container health probes |
| Add | — | `django-debug-toolbar` in `requirements-dev.txt` |

**Implementation:**

1. Search codebase for each deprecated package usage:
   ```bash
   grep -rn "import pytz" .
   grep -rn "from pytz" .
   grep -rn "import unipath" .
   grep -rn "from unipath" .
   grep -rn "import dotenv" .
   ```

2. Replace `pytz` imports:
   ```python
   # BEFORE
   import pytz
   tz = pytz.timezone('Asia/Almaty')
   aware_dt = tz.localize(naive_dt)

   # AFTER
   from zoneinfo import ZoneInfo
   tz = ZoneInfo('Asia/Almaty')
   aware_dt = naive_dt.replace(tzinfo=tz)
   ```

3. Replace `Unipath` usage with `pathlib`:
   ```python
   # BEFORE
   from unipath import Path
   BASE_DIR = Path(__file__).ancestor(3)

   # AFTER
   from pathlib import Path
   BASE_DIR = Path(__file__).resolve().parent.parent.parent
   ```

4. Add `django-health-check`:
   ```python
   # core/settings.py
   INSTALLED_APPS = [
       # ...
       'health_check',
       'health_check.db',
       'health_check.cache',
       'health_check.storage',
   ]

   # core/urls.py
   path('health/', include('health_check.urls')),
   ```

5. Update Docker/Nginx health probe to hit `/health/`.

---

### 6.2 Remove Legacy Template Views

**Files to modify:** `core/urls.py`, then delete old view files

**Implementation:**

1. First, verify no traffic hits legacy routes (check access logs or add logging middleware for 2 weeks).

2. Remove from `core/urls.py`:
   ```python
   # REMOVE these lines:
   path("", include("apps.authentication.urls")),
   path("pages/", include("apps.home.urls")),
   ```

3. Do NOT delete the old view files yet — move to an `_archive/` directory:
   ```bash
   mkdir _archive
   mv apps/home/views.py _archive/home_views_legacy.py
   mv apps/lesson/views.py _archive/lesson_views_legacy.py
   mv apps/authentication/views.py _archive/auth_views_legacy.py
   ```

4. Remove old template URL files:
   ```bash
   mv apps/home/urls.py _archive/home_urls_legacy.py
   mv apps/lesson/urls.py _archive/lesson_urls_legacy.py
   ```

5. Remove unused template files in `templates/` directory.

6. Run full test suite.

---

## Appendix: Execution Order

> **Execute in this order. Each batch depends on the previous one being complete.**

```
Batch 1 — Security (do first, no exceptions):
  ├── 1.1 Fix password reset flow
  ├── 1.2 Add rate limiting
  ├── 1.3 Fix silent except in logout
  ├── 1.4 Lock down CORS
  └── 1.5 Restrict school-groups

Batch 2 — Testing (unlocks safe refactoring):
  ├── 2.1 Test infrastructure (pytest, factories, conftest)
  ├── 2.2 Permission tests
  ├── 2.3 Grade calculation tests
  ├── 2.4 Auth flow tests
  └── 2.5 GitHub Actions CI

Batch 3 — Code structure:
  ├── 3.1 Consolidate permission classes
  ├── 3.2 Extract service layer
  ├── 3.3 Split home/api/views.py
  └── 6.1 Dependency cleanup

Batch 4 — Performance:
  ├── 4.1 Add database indexes
  ├── 4.2 Fix SubjectGradesAPIView
  ├── 4.3 Redis caching
  └── 4.4 Add pagination

Batch 5 — Data integrity:
  ├── 3.4 Unify notification models
  ├── 3.5 Standardize error messages
  ├── 5.1 Quarter grade snapshots
  ├── 5.2 Audit logging
  └── 5.3 Soft delete

Batch 6 — New features & cleanup:
  ├── 5.4 Academic year rollover
  ├── 5.5 Teacher workload dashboard
  └── 6.2 Remove legacy views
```
