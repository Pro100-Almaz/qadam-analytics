import json
from sections import section_prompts


def generate_extracurricular_prompt(student_data: dict, basic_info: str) -> tuple[str, str]:
    system_prompt = f"""
            Currently, you have to process the data related to the student's extracurricular activities and give the report on that
            according to the provided descriptions. 

            {section_prompts.extracurricular}
    """

    user_prompt = f"""
        Generate a qualitative analysis report of extracurricular activities for:

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
        Remember: output ONLY qualitative text analysis. NO numbers, NO percentages, NO scores in your response.
    """

    return system_prompt, user_prompt