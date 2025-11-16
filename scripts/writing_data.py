import os
from google.oauth2.service_account import Credentials
import gspread

from scripts.reading_data import SPREADSHEET_URL

CREDENTIALS_PATH = os.environ['SERVICE_ACCOUNT_FILE_INTERNAL']

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive  '
]

def get_writable_sheet(sheet_name):
    writable_credentials = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    writable_client = gspread.authorize(writable_credentials)
    spreadsheet = writable_client.open_by_url(SPREADSHEET_URL)
    return spreadsheet.worksheet(sheet_name)