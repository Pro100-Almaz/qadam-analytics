"""Quarter-grade helpers shared by the API, services and reporting.

Extracted from `apps.home.repo.students` so that live code does not depend on
the legacy server-rendered view layer. Pure domain logic — no request, no
template, no permission handling.
"""

def grade_identifier(percent):
    """Convert percentage to grade (2-5 scale)."""
    if percent > 80:
        return 5
    elif percent > 60:
        return 4
    elif percent > 40:
        return 3
    else:
        return 2
