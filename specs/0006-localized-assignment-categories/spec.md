---
id: 0006
slug: localized-assignment-categories
title: Assignment category names in en / ru / kk, chosen by Accept-Language
status: shipped
owner: bekzhan
created: 2026-09-30
updated: 2026-09-30
---

# 0006 — Localized assignment categories

## Problem

`AssignmentCategory.name` (spec 0005) is a single string, so
`GET /api/v1/assignment-categories/` returns the same name whatever the user's
language. The frontend is used in English, Russian and Kazakh and sends an
`Accept-Language` header with every request, but nothing in the API reads it
for data. On top of that, `settings.LANGUAGES` lists Kazakh as `kz`, which is
not a language code. Browsers and the frontend send `kk`, so Kazakh is never
matched.

## Goals

- G-1 An admin enters every category name in English, Russian and Kazakh.
- G-2 The API returns the name in the language of the `Accept-Language`
  header, and English when the header is missing or names another language.
- G-3 The mechanism is general, so other models can be made translatable later
  by registering them, with no new plumbing.

## Non-goals

- Translating any model other than `AssignmentCategory`. Others come later, one by one.
- Translating the category `code`. It is an identifier and stays language-neutral.
- UI strings, error messages, or the admin interface's own language.
- A `?lang=` query parameter or a per-user language preference.
- Renaming the `kz` value in `student_report` (the report-language choice,
  `apps/student_report/models.py`). It is a separate setting that doesn't come from `Accept-Language`.

## Affected roles

| Role (Django Group) | Change |
|---|---|
| Admin | Category add/change form has name fields for en, ru and kk. All three are required. |
| Every API user | `name` in `assignment-categories/` (and `category_name` on assignments) follows `Accept-Language`. |

## Acceptance criteria

- **AC-1** — In `/admin/`, adding a category without any one of the en, ru or
  kk names fails validation, and no row is created.
- **AC-2** — `GET /api/v1/assignment-categories/` with `Accept-Language: ru`
  returns the Russian names, with `kk` the Kazakh names, and with `en` the English ones.
- **AC-3** — With no `Accept-Language` header, or one naming an unsupported
  language (e.g. `de`), the response is in English.
- **AC-4** — Regional and weighted headers resolve: `ru-RU`, and
  `kk-KZ,kk;q=0.9,en;q=0.8` give Russian and Kazakh respectively.
- **AC-5** — Existing categories keep their current name as the English name,
  and the four seeded ones get Russian and Kazakh names from the migration.
- **AC-6** — `category_name` on `GET /api/v1/subject-assignments/` follows the same language rule.
- **AC-7** — The response shape is unchanged: `[{"id", "code", "name"}]`.
  `name` is a single string, not an object of translations.

## API contract

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/assignment-categories/` | Authenticated | `name` localized by `Accept-Language` (en default). Response adds `Content-Language`. |

```http
GET /api/v1/assignment-categories/
Accept-Language: kk

[{"id": 2, "code": "exam", "name": "Емтихан"}, ...]
```

## Data model

- `django-modeltranslation` registers `AssignmentCategory.name` for `en`, `ru` and `kk`.
  It adds the columns `name_en`, `name_ru` and `name_kk`. `name` reads the active
  language and falls back to `en`.
- `settings.LANGUAGES` becomes `en`, `ru`, `kk`. `LANGUAGE_CODE` stays `en`.
  `django.middleware.locale.LocaleMiddleware` is already installed and sets the
  active language from `Accept-Language`.
- Migration: additive columns, plus a data step that fills `name_en` from the
  existing `name` and sets ru/kk names for the seeded codes. Reversible.

## Permissions

Unchanged at all three tiers.

## Non-functional

- **Performance** — no extra queries. The translations are columns on the same row.
- **Security** — none.
- **Migrations** — additive and reversible. No downtime.

## Open questions

- [x] Library: `django-modeltranslation` (approved 2026-09-30) rather than
  hand-written `name_en/name_ru/name_kk` fields. It is opt-in per model and
  field, so nothing but `AssignmentCategory.name` is translated.
