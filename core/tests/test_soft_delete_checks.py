"""Spec 0014, AC-12 — `softdelete.E001` flags a hard-delete CASCADE child."""

from core import checks


def test_ac12_check_flags_hard_cascade_child(monkeypatch):
    # The real tree is clean: every CASCADE child of a soft-deletable model is
    # soft-deletable itself or on the exemption list.
    assert checks.check_soft_delete_cascades_stay_soft() == []

    # admin.LogEntry CASCADEs from the soft-deletable CustomUser. Take it off
    # the exemption list and it is exactly the case the check exists for.
    monkeypatch.delitem(checks.SOFT_DELETE_CASCADE_EXEMPT, 'admin.LogEntry')

    errors = checks.check_soft_delete_cascades_stay_soft()

    assert [e.id for e in errors] == ['softdelete.E001']
    assert 'admin.LogEntry.user' in errors[0].msg
    assert 'authentication.CustomUser' in errors[0].msg
