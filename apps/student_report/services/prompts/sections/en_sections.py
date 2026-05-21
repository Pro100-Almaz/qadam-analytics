en_section_prompts = {
    "summary": """
    Generate ONLY this JSON structure:
    {
        "summary": "2-3 sentence executive summary of overall performance (NO numbers)"
    }
    """,
    "overall_assessment": """
    Generate ONLY this JSON structure:
    {   
        "overall_assessment": {
             "score_label": "Excellent|Good|Average|Below Average|Needs Attention",
             "description": "1 paragraph overall assessment (NO numbers, NO percentages)"
           }
    }
    """,
    "subject_analyses": """
    Generate ONLY this JSON structure:
    {
        "subject_analyses": {
             "SubjectName": {
               "analysis": "2-3 sentences about this subject performance (NO grades, NO percentages)",
               "recommendation": "Specific actionable recommendation for this subject"
             }
           }
    }
    """,
    "strengths": """
    Generate ONLY this JSON structure:
    {
        "strengths": [
             {
               "area": "Short strength title",
               "description": "1-2 sentence detail (NO numbers)"
             }
           ],
    }
    """,
    "areas_for_improvement": """
    Generate ONLY this JSON structure:
    {
        "areas_for_improvement": [
             {
               "area": "Short area title",
               "description": "1-2 sentence detail (NO numbers)",
               "suggested_action": "Concrete step the student/teacher can take"
             }
           ],
    }
    """,
    "psychological_profile": """
    Generate ONLY this JSON structure:
    {
        "psychological_profile": {
             "summary": "Brief overview of psychological state",
             "observations": ["observation 1", "observation 2"],
             "recommendations": ["recommendation 1"]
           }
    }
    """,
    "extracurricular": """
    Generate ONLY this JSON structure:
    {
        "extracurricular": {
             "summary": "Brief overview of non-academic activities",
             "highlights": ["highlight 1", "highlight 2"]
           }
    }
    """,
    "recommendations": """
    Generate ONLY this JSON structure:
    {
        "recommendations": {{
             "for_teachers": ["actionable recommendation 1", "actionable recommendation 2"],
             "for_parents": ["actionable recommendation 1", "actionable recommendation 2"],
             "for_student": ["actionable recommendation 1", "actionable recommendation 2"]
           }}
    }
    """,
    "conclusion": """
    Generate ONLY this JSON structure:
    {
       "conclusion": "2-3 sentence forward-looking closing statement (NO numbers)"
    }
    """,


}