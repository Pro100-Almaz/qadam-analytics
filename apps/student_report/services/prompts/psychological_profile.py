import json

from .additional.user_descriptions import user_descriptions
from .additional.system_descriptions import sys_descriptions
from .sections.en_sections import en_section_prompts
from .sections.kz_sections import kz_section_prompts
from .sections.ru_sections import ru_section_prompts
from .additional.supportive import REMINDERS

def generate_psychological_prompt(student_data: dict, basic_info: str, language: str) -> tuple[str, str]:

    if language == 'en':
        section_prompts = en_section_prompts
    elif language == 'ru':
        section_prompts = ru_section_prompts
    else:
        section_prompts = kz_section_prompts

    system_description = sys_descriptions['psychological_profile'][language]


    system_prompt = f"""
            {system_description}

            {section_prompts['psychological_profile']}
    """


    user_prompt = f"""
        {user_descriptions['psychological_profile'][language]}
        {basic_info}
     
        ## Psychological States
        ```json
        {json.dumps(student_data['psychological_states'], ensure_ascii=False, indent=2, default=str)}
        ```
        {REMINDERS[language]}
    """


    return system_prompt, user_prompt