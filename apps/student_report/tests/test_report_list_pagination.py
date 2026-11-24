"""The per-student report list honours page_size (spec 0019)."""
from apps.student_report.models import StudentReport
from core.factories import AdminUserFactory


def test_ac31_reports_honour_page_size(authenticated_client, student, academic_year):
    reports = [
        StudentReport.objects.create(student=student, academic_year=academic_year, quarter=q)
        for q in (1, 2, 3)
    ]
    client = authenticated_client(AdminUserFactory())
    url = f'/api/v1/students/{student.pk}/reports/'

    page1 = client.get(url + '?page_size=2').data
    page2 = client.get(url + '?page_size=2&page=2').data

    assert page1['count'] == 3
    # Newest first; the id breaks ties when created_at is equal.
    assert [r['id'] for r in page1['results'] + page2['results']] == [
        r.id for r in reversed(reports)
    ]
    assert len(client.get(url).data['results']) == 3   # default page of 20
