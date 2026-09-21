import json

from apps.student_report.services.prompts.additional.user_descriptions import user_descriptions
from apps.student_report.services.prompts.additional.system_descriptions import sys_descriptions
from apps.student_report.services.prompts.sections.en_sections import en_section_prompts
from apps.student_report.services.prompts.sections.kz_sections import kz_section_prompts
from apps.student_report.services.prompts.sections.ru_sections import ru_section_prompts
from apps.student_report.services.prompts.additional.supportive import REMINDERS


def generate_summary_prompt(student_data: dict, subjects: str, basic_info: str, language: str) -> tuple[str, str]:

    if language == 'en':
        section_prompts = en_section_prompts
    elif language == 'ru':
        section_prompts = ru_section_prompts
    else:
        section_prompts = kz_section_prompts


    system_description = sys_descriptions['summary'][language]

    system_prompt = f"""
            {system_description}

            {section_prompts['summary']}
    """

    user_prompt = f"""
        {user_descriptions['summary'][language]}

        {basic_info}

        ### Grades by Subject and Quarter
        ```json
        {json.dumps(student_data['grades'], ensure_ascii=False, indent=2, default=str)}
        ```

        ### Quarter-over-Quarter Trends
        ```json
        {json.dumps(student_data['trends'], ensure_ascii=False, indent=2, default=str)}
        ```

        ## Psychological States
        ```json
        {json.dumps(student_data['psychological_states'], ensure_ascii=False, indent=2, default=str)}
        ```

        ## Achievements
        ```json
        {json.dumps(student_data['achievements'], ensure_ascii=False, indent=2, default=str)}
        ```

        ## Club Activity
        ```json
        {json.dumps(student_data['clubs'], ensure_ascii=False, indent=2, default=str)}
        ```

        {REMINDERS[language]}
    """

    return system_prompt, user_prompt