import json

from apps.student_report.services.prompts.additional.supportive import REMINDERS
from apps.student_report.services.prompts.additional.system_descriptions import sys_descriptions
from apps.student_report.services.prompts.additional.user_descriptions import user_descriptions
from apps.student_report.services.prompts.sections.en_sections import en_section_prompts
from apps.student_report.services.prompts.sections.kz_sections import kz_section_prompts
from apps.student_report.services.prompts.sections.ru_sections import ru_section_prompts


def generate_assessment_prompt(student_data: dict, basic_info: str, language: str) -> tuple[str, str]:

    if language == 'en':
        section_prompts = en_section_prompts
    elif language == 'ru':
        section_prompts = ru_section_prompts
    else:
        section_prompts = kz_section_prompts

    system_description = sys_descriptions['overall_assessment'][language]


    system_prompt = f"""
            {system_description}
            
            {section_prompts['overall_assessment']}
    """


    user_prompt = f"""
        {user_descriptions['overall_assessment'][language]}
        
        {basic_info}

        ## Academic Data

        ### Grades by Subject and Quarter
        ```json
        {json.dumps(student_data['grades'], ensure_ascii=False, indent=2, default=str)}
        ```

        ### Quarter-over-Quarter Trends
        ```json
        {json.dumps(student_data['trends'], ensure_ascii=False, indent=2, default=str)}
        ```

        ### Class Averages by Subject
        ```json
        {json.dumps(student_data['class_context'], ensure_ascii=False, indent=2, default=str)}
        ```
        {REMINDERS[language]}
    """


    return system_prompt, user_prompt