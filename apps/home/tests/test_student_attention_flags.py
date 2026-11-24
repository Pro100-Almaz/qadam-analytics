"""attention_flags and absence_streak (spec 0019). Pure functions, no database."""
from datetime import date

import pytest
from django.conf import settings

from apps.home.services import absence_streak, attention_flags


def metrics(**overrides):
    base = {
        'subjects': [],
        'absence_streak': 0,
        'attendance_rate': None,
        'overdue_homework': 0,
        'wellbeing': None,
    }
    return {**base, **overrides}


def subject(grade, previous=None, name='Algebra', subject_id=7):
    return {
        'subject_id': subject_id, 'subject_name': name,
        'grade': grade, 'previous_grade': previous,
    }


def flags(thresholds=None, **overrides):
    return attention_flags(
        metrics(**overrides), thresholds or settings.STUDENT_ATTENTION_THRESHOLDS,
    )


def codes(result):
    return [(f['code'], f['severity']) for f in result]


def test_ac12_low_grade_flag_is_critical():
    [flag] = flags(subjects=[subject(2)])
    assert flag == {
        'code': 'low_grade', 'severity': 'critical',
        'subject_id': 7, 'subject_name': 'Algebra', 'params': {'grade': 2},
    }
    assert flags(subjects=[subject(3), subject(None)]) == []


def test_ac13_falling_grade_flag_never_in_q1():
    [flag] = flags(subjects=[subject(3, previous=4)])
    assert (flag['code'], flag['severity'], flag['params']) == (
        'falling_grade', 'warning', {'from': 4, 'to': 3},
    )
    # Q1 has no previous quarter: the service passes previous_grade=None.
    assert flags(subjects=[subject(3, previous=None)]) == []
    assert flags(subjects=[subject(4, previous=4)]) == []


@pytest.mark.parametrize('days, expected', [
    (2, []),
    (3, [('absence_streak', 'warning')]),
    (4, [('absence_streak', 'warning')]),
    (5, [('absence_streak', 'critical')]),
])
def test_ac14_absence_streak_warning_and_critical(days, expected):
    result = flags(absence_streak=days)
    assert codes(result) == expected
    if result:
        assert result[0]['params'] == {'days': days}
        assert result[0]['subject_id'] is None


def test_ac14_streak_counts_trailing_fully_absent_days():
    d = date(2026, 11, 2)
    days = [
        (d.replace(day=2), 2, 2),
        (d.replace(day=3), 2, 1),   # partly present: breaks the run
        (d.replace(day=4), 1, 1),
        (d.replace(day=6), 3, 3),   # the 5th was not recorded and does not break it
        (d.replace(day=9), 1, 1),
    ]
    assert absence_streak(days) == 3
    assert absence_streak([]) == 0
    assert absence_streak(days + [(d.replace(day=10), 1, 0)]) == 0


@pytest.mark.parametrize('rate, expected', [
    (None, []),
    (85.0, []),
    (84.9, [('low_attendance', 'warning')]),
    (70.0, [('low_attendance', 'warning')]),
    (69.9, [('low_attendance', 'critical')]),
])
def test_ac15_low_attendance_thresholds_and_null_rate(rate, expected):
    result = flags(attendance_rate=rate)
    assert codes(result) == expected
    if result:
        assert result[0]['params'] == {'rate': rate}


def test_ac16_overdue_homework_flag():
    assert flags(overdue_homework=2) == []
    [flag] = flags(overdue_homework=3)
    assert (flag['code'], flag['severity'], flag['params']) == (
        'overdue_homework', 'warning', {'count': 3},
    )


def test_ac17_wellbeing_drop_flag():
    assert flags(wellbeing={'name': 'Mood', 'score': 3}) == []
    [flag] = flags(wellbeing={'name': 'Mood', 'score': 2})
    assert (flag['code'], flag['severity'], flag['params']) == (
        'wellbeing_drop', 'warning', {'score': 2, 'name': 'Mood'},
    )


def test_ac18_attention_sorted_critical_first():
    result = flags(
        subjects=[
            subject(3, previous=5, name='Physics', subject_id=9),
            subject(2, name='Algebra', subject_id=7),
            subject(2, name='Biology', subject_id=8),
        ],
        absence_streak=5,
        overdue_homework=4,
    )
    assert [(f['code'], f['severity'], f['subject_name']) for f in result] == [
        ('absence_streak', 'critical', None),
        ('low_grade', 'critical', 'Algebra'),
        ('low_grade', 'critical', 'Biology'),
        ('falling_grade', 'warning', 'Physics'),
        ('overdue_homework', 'warning', None),
    ]


def test_ac19_threshold_setting_override_flips_flag(settings):
    assert flags(overdue_homework=1) == []

    settings.STUDENT_ATTENTION_THRESHOLDS = {
        **settings.STUDENT_ATTENTION_THRESHOLDS,
        'overdue_homework': {'warning': 1},
    }

    assert codes(flags(overdue_homework=1)) == [('overdue_homework', 'warning')]
