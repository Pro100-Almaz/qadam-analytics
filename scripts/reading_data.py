import os

from decouple import config
from google.oauth2.service_account import Credentials
import gspread

CREDENTIALS_PATH = os.environ['SERVICE_ACCOUNT_FILE_INTERNAL']

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

credentials = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
client = gspread.authorize(credentials)

SPREADSHEET_URL = config('SPREADSHEET_URL')

def get_sheets_data():
    sheet = client.open_by_url(SPREADSHEET_URL)
    all_sheets = {}
    for worksheet in sheet.worksheets():
        title = worksheet.title.lower()
        if 'teacher' in title:
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password",
                "Academic Year", "Gender", "EmploymentType", "Subjects",
                "WorkingHours"
            ])
        elif 'supervisor' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password",
            ])
        elif 'parent' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password", "Students"
            ])
        elif 'subject' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Name", "Status", "LanguageGroup", "MaximumPoints", "Teacher",
                "AddedBy", "AcademicYear"
            ])
        elif 'lesson' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Title", "Description", "Subject", "MaxPoints", "Quarter", "Unit", "Status", "Group"
            ])
        elif 'topic' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'LessonTitle', 'TopicTitle', 'Weight', 'ParentTopic', 'CommentTemplate'
            ])
        elif 'grad' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'LessonTitle', 'TopicTitle', 'StudentNickname', 'Grade', 'Comment', 'CommentSelected'
            ])
        elif 'state' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'Name', 'Comment', 'Score', 'StudentNickname', 'AddedBy'
            ])

        else: #studentter
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password",
                "Academic Year", "Class", "School Group (Orda)", "Subjects"
            ])
        all_sheets[worksheet.title] = records
    return all_sheets
