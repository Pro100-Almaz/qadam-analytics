from apps.student_report.services.prompts.additional.supportive import REMINDERS
from apps.student_report.services.prompts.sections.conclusion_prompts import conclusion_sys_prompts, conclusion_user_description


def generate_conclusion_prompt(total_context: str, language: str) -> tuple[str, str]:

    conclusion_system_prompt = conclusion_sys_prompts[language]


    user_prompt = f"""
        {conclusion_user_description[language]}
        {total_context}
        
        {REMINDERS[language]}
    """

    return conclusion_system_prompt, user_prompt

