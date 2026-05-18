import json
import time
import logging

import openai
from django.conf import settings

from apps.student_report.services.prompts.conclusion import generate_conclusion_prompt

logger = logging.getLogger(__name__)

REQUIRED_KEYS = [
    'summary', 'overall_assessment', 'subject_analyses',
    'strengths', 'areas_for_improvement', 'psychological_profile',
    'extracurricular', 'recommendations', 'conclusion',
]


def _get_ai_response(system_prompt:str, user_prompt:str):
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=settings.AI_REPORT_MODEL,
        max_tokens=settings.AI_REPORT_MAX_TOKENS,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

def generate_report(report_id: int) -> None:
    from apps.student_report.models import StudentReport
    from apps.student_report.services.data_collector import collect_student_data
    from apps.student_report.services.prompt_builder import build_report_prompt

    report = StudentReport.objects.select_related(
        'student', 'academic_year'
    ).get(pk=report_id)

    try:
        report.status = StudentReport.Status.GENERATING
        report.save(update_fields=['status'])

        student_data = collect_student_data(
            student_id=report.student_id,
            quarter=report.quarter,
        )
        report.input_snapshot = json.loads(
            json.dumps(student_data, default=str)
        )
        report.save(update_fields=['input_snapshot'])

        prompt_categories = build_report_prompt(
            student_data=student_data,
            language=report.language,
            quarter=report.quarter,
        )

        used_tokens = 0
        start_time = time.monotonic()


        for system_prompt, user_prompt in prompt_categories:
            response = _get_ai_response(system_prompt, user_prompt)
            raw_text = response.choices[0].message.content
            report_data = json.loads(raw_text)
            report.report_data.update(report_data)
            used_tokens += response.usage.prompt_tokens + response.usage.completion_tokens


        missing = [k for k in REQUIRED_KEYS if k not in report.report_data]
        if missing:
            raise ValueError(f"AI response missing required keys: {missing}")


        conclusion = generate_conclusion_prompt(report.report_data, report.language)
        response = _get_ai_response(conclusion.first, conclusion.second)
        raw_text = response.choices[0].message.content

        report_data = json.loads(raw_text)
        report.report_data.update(report_data)
        used_tokens += response.usage.prompt_tokens + response.usage.completion_tokens

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        report.status = StudentReport.Status.COMPLETED
        report.model_used = settings.AI_REPORT_MODEL
        report.tokens_used = used_tokens
        report.generation_time_ms = elapsed_ms
        report.save(update_fields=[
            'report_data', 'status', 'model_used',
            'tokens_used', 'generation_time_ms',
        ])

        logger.info(
            "Report %d generated in %dms (%d tokens)",
            report.pk, elapsed_ms, report.tokens_used,
        )

    except json.JSONDecodeError as e:
        report.status = StudentReport.Status.FAILED
        report.error_message = f"Failed to parse AI response as JSON: {e}"
        report.save(update_fields=['status', 'error_message'])
        logger.error("Report %d JSON parse error: %s", report.pk, e)

    except openai.APIError as e:
        report.status = StudentReport.Status.FAILED
        report.error_message = f"OpenAI API error: {e}"
        report.save(update_fields=['status', 'error_message'])
        logger.error("Report %d API error: %s", report.pk, e)

    except Exception as e:
        report.status = StudentReport.Status.FAILED
        report.error_message = f"Unexpected error: {e}"
        report.save(update_fields=['status', 'error_message'])
        logger.exception("Report %d unexpected error", report.pk)
