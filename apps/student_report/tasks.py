import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report_task(self, report_id: int):
    from apps.student_report.services.generator import generate_report
    from apps.student_report.models import StudentReport

    try:
        generate_report(report_id)
    except Exception as exc:
        logger.exception("Celery task failed for report %d", report_id)
        raise self.retry(exc=exc)

    report = StudentReport.objects.select_related(
        'student__user', 'generated_by', 'academic_year'
    ).get(pk=report_id)

    if report.status == StudentReport.Status.COMPLETED:
        _send_completion_email(report)
    elif report.status == StudentReport.Status.FAILED:
        _send_failure_email(report)


def _send_completion_email(report):
    if not report.generated_by or not report.generated_by.email:
        return

    student_name = report.student.user.get_full_name()
    subject = f"Report ready: {student_name} — Q{report.quarter}"
    message = (
        f"The student report for {student_name} "
        f"({report.academic_year}, Quarter {report.quarter}) "
        f"has been generated successfully.\n\n"
        f"You can view it in the Qadam dashboard."
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[report.generated_by.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception("Failed to send completion email for report %d", report.pk)


def _send_failure_email(report):
    if not report.generated_by or not report.generated_by.email:
        return

    student_name = report.student.user.get_full_name()
    subject = f"Report failed: {student_name} — Q{report.quarter}"
    message = (
        f"The student report for {student_name} "
        f"({report.academic_year}, Quarter {report.quarter}) "
        f"failed to generate.\n\n"
        f"Error: {report.error_message}\n\n"
        f"Please try again or contact support."
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[report.generated_by.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception("Failed to send failure email for report %d", report.pk)
