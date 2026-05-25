import json
from .additional.supportive import REMINDERS
from .additional.system_descriptions import sys_descriptions
from .additional.user_descriptions import user_descriptions
from .sections.en_sections import en_section_prompts
from .sections.kz_sections import kz_section_prompts
from .sections.ru_sections import ru_section_prompts


def generate_subject_prompt(student_data: dict, subjects: str, basic_info: str, language: str) -> tuple[str, str]:

    if language == 'en':
        section_prompts = en_section_prompts
    elif language == 'ru':
        section_prompts = ru_section_prompts
    else:
        section_prompts = kz_section_prompts


    system_description = sys_descriptions['subject_analyses'][language]

    system_prompt = f"""
            {system_description}
            {subjects}

            
            {section_prompts['subject_analyses']}
        """


    user_prompt = f"""
        {user_descriptions['subject_analyses'][language]}
        
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