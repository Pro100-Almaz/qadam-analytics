import json

from apps.student_report.services.prompts.areas_for_improvement import generate_improvement_prompt
from apps.student_report.services.prompts.extracurricular import generate_extracurricular_prompt
from apps.student_report.services.prompts.overall_assessments import generate_assessment_prompt
from apps.student_report.services.prompts.psychological_profile import generate_psychological_prompt
from apps.student_report.services.prompts.strengths import generate_strengths_prompt
from apps.student_report.services.prompts.subject_analysis import generate_subject_prompt
from apps.student_report.services.prompts.summary import generate_summary_prompt

LANGUAGE_INSTRUCTIONS = {
    'ru': 'Напиши весь отчёт полностью на русском языке.',
    'kk': 'Бүкіл есепті толығымен қазақ тілінде жаз.',
    'en': 'Write the entire report in English.',
}


def build_report_prompt(student_data: dict, language: str, quarter: int) -> dict:
    period = f"Quarter {quarter}"
    personal = student_data['personal']

    subjects_list = list(student_data['grades'].get('subjects', {}).keys())
    subjects_json = json.dumps(subjects_list, ensure_ascii=False)

    base_system_prompt = """
        You are an experienced educational analyst at a school in Kazakhstan.
        You write detailed, actionable student performance reports for teachers and administrators.
        
        {language_instructions}
        
        IMPORTANT: All numeric data (grades, percentages, averages, trends) is already provided separately from the database.
        Do NOT include any numbers, grades, or percentages in your response.
        Your job is ONLY to provide qualitative text analysis and recommendations based on the data.
        Please avoid using the student's name. For example, if the student's name is Karim, try to replace his name with pronouns
        like he, she, or "the student".
        
        You must respond with ONLY a valid JSON object (no markdown, no preamble, no commentary outside the JSON).
        
        {custom_system_prompt}
        
        Rules:
        - NEVER invent or repeat numbers. The frontend displays grades from the database — your text must NOT include any percentages, scores, or numeric values.
        - Instead of "scored 91%", say "demonstrates excellent results" or "significantly above class average".
        - Instead of "improved by 8%", say "shows notable improvement" or "significant progress this quarter".
        - Base EVERY claim on the provided data. Do not invent facts.
        - Be constructive — frame weaknesses as growth opportunities.
        - Be specific — "improve Math" is bad; "practice algebraic word problems 3x/week" is good.
        - If psychological state data is empty, set psychological_profile.summary to "No data available" and leave observations/recommendations as empty arrays.
        - If achievement/reading/club data is empty, set extracurricular.summary to "No extracurricular data recorded" and highlights as empty array.
        - Keep the tone professional but warm — this may be shared with parents.
        
        Extra: use the following grade scale to make the analysis more qualitative: 
                grade_scale = [
                    (85, "Excellent"),
                    (70, "Good"),
                    (50, "Satisfactory"),
                    (35, "Pass"),
                    (0, "Needs Improvement"),
                ]
    """

    def get_custom_system_prompt(prompt: str) -> str:
        return base_system_prompt.format(
            language_instructions=LANGUAGE_INSTRUCTIONS[language],
            custom_system_prompt=prompt
        )

    def get_basic_context_data():
        return f"""
               **Student:** {personal['full_name']}
               **Class:** {personal['class_group']}
               **Academic Year:** {personal['academic_year']}
               **Report Period:** {period}
           """

    result = {} # category : (custom_system_prompt, custom_user_prompt)

    categories = ['summary', 'subject_analyses', 'strengths', 'areas_for_improvement', 'psychological_profile', 'extracurricular', 'recommendations']

    for category in categories:

        if category == 'summary':
            system_prompt, user_prompt = generate_summary_prompt(student_data, subjects_json, get_basic_context_data())

        elif category == 'subject_analyses':
            system_prompt, user_prompt = generate_subject_prompt(student_data, subjects_json, get_basic_context_data())

        elif category == 'strengths':
            system_prompt, user_prompt = generate_strengths_prompt(student_data, get_basic_context_data())

        elif category == 'overall_assessment':
            system_prompt, user_prompt = generate_assessment_prompt(student_data, get_basic_context_data())

        elif category == 'areas_for_improvement':
            system_prompt, user_prompt = generate_improvement_prompt(student_data, get_basic_context_data())

        elif category == 'psychological_profile':
            system_prompt, user_prompt = generate_psychological_prompt(student_data, get_basic_context_data())

        elif category == 'extracurricular':
            system_prompt, user_prompt = generate_extracurricular_prompt(student_data, get_basic_context_data())

        elif category == 'recommendations':
            system_prompt, user_prompt = generate_strengths_prompt(student_data, get_basic_context_data())

        custom_system_prompt = get_custom_system_prompt(system_prompt)
        result[category] = (custom_system_prompt, user_prompt)

    return result

