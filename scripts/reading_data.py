import os
from json import JSONDecodeError

from decouple import config
from google.oauth2.service_account import Credentials
import gspread

CREDENTIALS_PATH = os.environ.get(
    "SERVICE_ACCOUNT_FILE_INTERNAL",
    config("SERVICE_ACCOUNT_FILE", default=None)
)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

if not CREDENTIALS_PATH:
    raise RuntimeError(
        "Google Sheets credentials path is not configured. Set "
        "SERVICE_ACCOUNT_FILE or SERVICE_ACCOUNT_FILE_INTERNAL."
    )

if not os.path.exists(CREDENTIALS_PATH):
    raise RuntimeError(
        f"Google Sheets credentials file does not exist: {CREDENTIALS_PATH}"
    )

if os.path.getsize(CREDENTIALS_PATH) == 0:
    raise RuntimeError(
        f"Google Sheets credentials file is empty: {CREDENTIALS_PATH}"
    )

try:
    credentials = Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES,
    )
except JSONDecodeError as exc:
    raise RuntimeError(
        f"Google Sheets credentials file is not valid JSON: {CREDENTIALS_PATH}"
    ) from exc

client = gspread.authorize(credentials)

SPREADSHEET_URL = config('SPREADSHEET_URL')

def get_sheets_data(only_sheets=None):
    only_sheets = {name.lower() for name in only_sheets} if only_sheets else None
    sheet = client.open_by_url(SPREADSHEET_URL)
    all_sheets = {}
    for worksheet in sheet.worksheets():
        title = worksheet.title.lower()
        if only_sheets is not None and title not in only_sheets:
            continue

        if 'teacher' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password",
                "Academic Year", "Gender", "EmploymentType", "Subjects",
                "WorkingHours", "ImportStatus"
            ])
        elif 'supervisor' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password", "ImportStatus"
            ])
        elif 'parent' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password", "Students", "ImportStatus"
            ])
        elif 'subject' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Name", "Status", "LanguageGroup", "MaximumPoints", "Teacher",
                "AddedBy", "AcademicYear", "ImportStatus"
            ])
        elif 'lesson' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                "Title", "Description", "Subject", "MaxPoints", "Quarter", "Unit", "Status", "Group", "ImportStatus"
            ])
        elif 'topic' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'LessonTitle', 'TopicTitle', 'Weight', 'ParentTopic', 'CommentTemplate', "ImportStatus"
            ])
        elif 'grad' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'LessonTitle', 'TopicTitle', 'StudentNickname', 'Grade', 'Comment', 'CommentSelected', "ImportStatus"
            ])
        elif 'state' in title.lower():
            records = worksheet.get_all_records(expected_headers=[
                'Name', 'Comment', 'Score', 'StudentNickname', 'AddedBy', "ImportStatus"
            ])

        else: #studentter
            records = worksheet.get_all_records(expected_headers=[
                "Nickname", "First Name", "Last Name", "Email", "Role", "School",
                "Address", "Phone (parent)", "Date of Birth", "Password",
                "Academic Year", "Class", "School Group (Orda)", "Subjects", "ImportStatus"
            ])
        all_sheets[worksheet.title] = records
    return all_sheets
