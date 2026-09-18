import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report_task(self, report_id: int, school_id: int = None):
    """Generate a student report inside its school's scope.

    A Celery prefork worker starts with a fresh, empty context — so the scope is
    UNSET and every scoped query fails closed. The task has to enter one itself.

    `school_id` is passed by the caller rather than derived from the report on
    purpose: deriving it would mean reading the report *before* a scope exists,
    which is the thing that cannot happen. It also means a replayed or forged
    task id cannot reach into another tenant — the scope comes from the enqueuer.

    It is optional for one release only. Tasks already queued when this deploys
    carry a single argument, and making it required would fail every one of them
    on the first worker restart. The fallback resolves the school unscoped, which
    is safe here because the report id is not client-supplied at that point.
    Make it required once the queue has drained.
    """
    from apps.student_report.services.generator import generate_report
    from apps.student_report.models import StudentReport
    from core.tenancy import all_schools, school_scope

    if school_id is None:
        logger.warning(
            "generate_report_task(%d) queued without school_id — pre-tenancy "
            "task, resolving it from the report", report_id,
        )
        with all_schools():
            school_id = (
                StudentReport.objects.filter(pk=report_id)
                .values_list('student__user__school_id', flat=True)
                .first()
            )
        if school_id is None:
            logger.error("Report %d has no school; nothing to do", report_id)
            return

    with school_scope(school_id):
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
