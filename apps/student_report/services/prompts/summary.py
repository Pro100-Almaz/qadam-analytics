import json
from .sections import section_prompts


def generate_summary_prompt(student_data: dict, subjects: str, basic_info: str) -> tuple[str, str]:
    system_prompt = f"""
            Currently, you have to provide a qualitative summary of the student's performance based on the provided data. 

            {section_prompts['summary']}
    """

    user_prompt = f"""
        Generate a qualitative summary report for:

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

        Remember: output ONLY qualitative text analysis. NO numbers, NO percentages, NO scores in your response.
    """

    return system_prompt, user_prompt