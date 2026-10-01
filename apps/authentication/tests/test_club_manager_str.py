import pytest

from core.factories import ClubManagerFactory


@pytest.mark.django_db
def test_club_manager_is_labelled_with_the_users_full_name():
    manager = ClubManagerFactory(user__first_name='Aigerim', user__last_name='Sadykova')
    assert str(manager) == 'Aigerim Sadykova'


@pytest.mark.django_db
def test_club_manager_without_a_name_falls_back_to_username():
    manager = ClubManagerFactory(user__first_name='', user__last_name='')
    assert str(manager) == manager.user.username
