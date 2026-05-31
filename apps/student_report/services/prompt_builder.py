import json

from apps.student_report.services.prompts.areas_for_improvement import generate_improvement_prompt
from apps.student_report.services.prompts.extracurricular import generate_extracurricular_prompt
from apps.student_report.services.prompts.overall_assessments import generate_assessment_prompt
from apps.student_report.services.prompts.psychological_profile import generate_psychological_prompt
from apps.student_report.services.prompts.strengths import generate_strengths_prompt
from apps.student_report.services.prompts.subject_analysis import generate_subject_prompt
from apps.student_report.services.prompts.recommendations import generate_recommendations_prompt
from apps.student_report.services.prompts.summary import generate_summary_prompt
from apps.student_report.services.base_sys_prompts.en_base_prompt import english_system_prompt
from apps.student_report.services.base_sys_prompts.kz_base_prompt import kazakh_system_prompt
from apps.student_report.services.base_sys_prompts.ru_base_prompt import russian_system_prompt
from apps.student_report.services.prompts.additional.supportive import BASIC_CONTEXT_DATA


def build_report_prompt(student_data: dict, language: str, quarter: int) -> dict:
    period = f"Quarter {quarter}"
    personal = student_data['personal']

    subjects_list = list(student_data['grades'].get('subjects', {}).keys())
    subjects_json = json.dumps(subjects_list, ensure_ascii=False)


    if language == 'en':
        base_system_prompt = english_system_prompt
    elif language == 'ru':
        base_system_prompt = russian_system_prompt
    else:
        base_system_prompt = kazakh_system_prompt


    def _get_custom_system_prompt(prompt: str) -> str:
        return base_system_prompt.format(custom_system_prompt=prompt)


    def _get_basic_context_data():
        return BASIC_CONTEXT_DATA[language].format(
            full_name=personal['full_name'],
            class_group=personal['class_group'],
            academic_year=personal['academic_year'],
            period=period
        )


    result = {} # category : (custom_system_prompt, custom_user_prompt)
    categories = ['summary', 'overall_assessment', 'subject_analyses', 'strengths', 'areas_for_improvement', 'psychological_profile', 'extracurricular', 'recommendations']

    for category in categories:

        if category == 'summary':
            system_prompt, user_prompt = generate_summary_prompt(student_data, subjects_json, _get_basic_context_data(), language)

        elif category == 'subject_analyses':
            system_prompt, user_prompt = generate_subject_prompt(student_data, subjects_json, _get_basic_context_data(), language)

        elif category == 'strengths':
            system_prompt, user_prompt = generate_strengths_prompt(student_data, _get_basic_context_data(), language)

        elif category == 'overall_assessment':
            system_prompt, user_prompt = generate_assessment_prompt(student_data, _get_basic_context_data(), language)

        elif category == 'areas_for_improvement':
            system_prompt, user_prompt = generate_improvement_prompt(student_data, _get_basic_context_data(), language)

        elif category == 'psychological_profile':
            system_prompt, user_prompt = generate_psychological_prompt(student_data, _get_basic_context_data(), language)

        elif category == 'extracurricular':
            system_prompt, user_prompt = generate_extracurricular_prompt(student_data, _get_basic_context_data(), language)

        elif category == 'recommendations':
            system_prompt, user_prompt = generate_recommendations_prompt(student_data, subjects_json, _get_basic_context_data(), language)

        custom_system_prompt = _get_custom_system_prompt(system_prompt)
        result[category] = (custom_system_prompt, user_prompt)

    return result

