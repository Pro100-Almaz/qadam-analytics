import json

from .additional.user_descriptions import user_descriptions
from .additional.system_descriptions import sys_descriptions
from .sections.en_sections import en_section_prompts
from .sections.kz_sections import kz_section_prompts
from .sections.ru_sections import ru_section_prompts
from .additional.supportive import REMINDERS

def generate_extracurricular_prompt(student_data: dict, basic_info: str, language: str) -> tuple[str, str]:

    if language == 'en':
        section_prompts = en_section_prompts
    elif language == 'ru':
        section_prompts = ru_section_prompts
    else:
        section_prompts = kz_section_prompts


    system_description = sys_descriptions['extracurricular'][language]

    system_prompt = f"""
            {system_description}

            {section_prompts['extracurricular']}
    """

    user_prompt = f"""
        {user_descriptions['extracurricular'][language]}

        {basic_info}

        ## Achievements
        ```json
        {json.dumps(student_data['achievements'], ensure_ascii=False, indent=2, default=str)}
        ```
        
        ## Reading Activity
        ```json
        {json.dumps(student_data['reading'], ensure_ascii=False, indent=2, default=str)}
        ```
        
        ## Club Activity
        ```json
        {json.dumps(student_data['clubs'], ensure_ascii=False, indent=2, default=str)}
        ```
        {REMINDERS[language]}
    """

    return system_prompt, user_prompt