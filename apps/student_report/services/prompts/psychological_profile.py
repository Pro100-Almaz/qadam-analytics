import json
from sections import section_prompts


def generate_psychological_prompt(student_data: dict, basic_info: str) -> tuple[str, str]:
    system_prompt = f"""
            Currently, you have to process the student's psychological profile. 

            {section_prompts.psychological_profile}
    """

    user_prompt = f"""
        Generate a qualitative psychological state analysis report for:

        {basic_info}
     
        ## Psychological States
        ```json
        {json.dumps(student_data['psychological_states'], ensure_ascii=False, indent=2, default=str)}
        ```
        Remember: output ONLY qualitative text analysis. NO numbers, NO percentages, NO scores in your response.
    """

    return system_prompt, user_prompt