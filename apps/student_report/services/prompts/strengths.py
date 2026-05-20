import json
from .sections import section_prompts


def generate_strengths_prompt(student_data: dict, basic_info: str) -> tuple[str, str]:
    system_prompt = f"""
            Currently, you have to process the provided information and give a qualitative report on the student's strengths. 

            {section_prompts['strengths']}
        """

    user_prompt = f"""
        Generate a qualitative strengths report for:

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