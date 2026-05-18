import json
from sections import section_prompts


def generate_assessment_prompt(student_data: dict, basic_info: str) -> tuple[str, str]:
    system_prompt = f"""
            Currently, you have to give the overall assessment of the student based on the grades, trends, class averages and other relevant data. 

            {section_prompts.overall_assessments}
    """

    user_prompt = f"""
        Generate a qualitative overall assessment for:

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
        Remember: output ONLY qualitative text analysis. NO numbers, NO percentages, NO scores in your response.
    """

    return system_prompt, user_prompt