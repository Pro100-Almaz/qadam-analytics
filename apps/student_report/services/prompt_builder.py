import json

LANGUAGE_INSTRUCTIONS = {
    'ru': 'Напиши весь отчёт полностью на русском языке.',
    'kk': 'Бүкіл есепті толығымен қазақ тілінде жаз.',
    'en': 'Write the entire report in English.',
}


def build_report_prompt(student_data: dict, language: str, quarter: int) -> tuple[str, str]:
    period = f"Quarter {quarter}"
    personal = student_data['personal']

    system_prompt = f"""You are an experienced educational analyst at a school in Kazakhstan.
You write detailed, actionable student performance reports for teachers and administrators.

{LANGUAGE_INSTRUCTIONS[language]}

You must respond with ONLY a valid JSON object (no markdown, no preamble, no commentary outside the JSON).

The JSON must have this exact structure:
{{
  "summary": "2-3 sentence executive summary of overall performance",
  "overall_assessment": {{
    "score_label": "Excellent|Good|Average|Below Average|Needs Attention",
    "description": "1 paragraph overall assessment"
  }},
  "academic_performance": {{
    "overview": "General academic narrative",
    "subject_analyses": [
      {{
        "subject": "Subject name",
        "grade_percentage": 85.0,
        "class_average": 72.0,
        "trend": "improving|declining|stable",
        "analysis": "2-3 sentences about this subject performance",
        "recommendation": "Specific actionable recommendation"
      }}
    ]
  }},
  "strengths": [
    {{
      "area": "Short strength title",
      "description": "1-2 sentence detail"
    }}
  ],
  "areas_for_improvement": [
    {{
      "area": "Short area title",
      "description": "1-2 sentence detail",
      "suggested_action": "Concrete step the student/teacher can take"
    }}
  ],
  "psychological_profile": {{
    "summary": "Brief overview of psychological state",
    "observations": ["observation 1", "observation 2"],
    "recommendations": ["recommendation 1"]
  }},
  "extracurricular": {{
    "summary": "Brief overview of non-academic activities",
    "highlights": ["highlight 1", "highlight 2"]
  }},
  "recommendations": {{
    "for_teachers": ["actionable recommendation 1", "actionable recommendation 2"],
    "for_parents": ["actionable recommendation 1", "actionable recommendation 2"],
    "for_student": ["actionable recommendation 1", "actionable recommendation 2"]
  }},
  "conclusion": "2-3 sentence forward-looking closing statement"
}}

Rules:
- Base EVERY claim on the provided data. Do not invent grades, scores, or facts.
- Compare the student to class averages when available.
- Be constructive — frame weaknesses as growth opportunities.
- Be specific — "improve Math" is bad; "practice algebraic word problems 3x/week" is good.
- If psychological state data is empty, set psychological_profile.summary to "No data available" and leave observations/recommendations as empty arrays.
- If achievement/reading/club data is empty, set extracurricular.summary to "No extracurricular data recorded" and highlights as empty array.
- Keep the tone professional but warm — this may be shared with parents."""

    user_prompt = f"""Generate a detailed student report for:

**Student:** {personal['full_name']}
**Class:** {personal['class_group']}
**Academic Year:** {personal['academic_year']}
**Report Period:** {period}

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

## Psychological States
```json
{json.dumps(student_data['psychological_states'], ensure_ascii=False, indent=2, default=str)}
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
```"""

    return system_prompt, user_prompt
