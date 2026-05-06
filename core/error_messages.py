from django.utils.translation import gettext_lazy as _

# Auth
USER_NOT_FOUND = _("User not found.")
INVALID_PASSWORD = _("Invalid password.")
PASSWORD_MISMATCH = _("Passwords do not match.")
PASSWORD_CHANGED = _("Password changed successfully.")
TOKEN_EXPIRED = _("Token has expired.")
TOKEN_REQUIRED = _("Token is required.")
INVALID_TOKEN = _("Invalid or expired token.")
INVALID_LINK = _("Invalid link or token.")
INVALID_CODE = _("Invalid code.")
ACCOUNT_DISABLED = _("This account has been disabled.")
REFRESH_TOKEN_REQUIRED = _("Refresh token is required.")
RESET_TOKEN_REQUIRED = _("Reset token is required.")
LOGOUT_FAILED = _("Logout failed. Please try again.")
NO_ACTIVE_RESET = _("No active reset request. Please request a new code.")
TOO_MANY_ATTEMPTS = _("Too many attempts. Please request a new code.")

# Permissions
NO_PERMISSION = _("You do not have permission to perform this action.")
NO_ACCESS_STUDENT = _("You do not have access to this student.")
NO_ACCESS_TEACHER = _("You do not have permission to view this teacher.")
NO_ACCESS_SUBJECT = _("You do not have permission to view this subject.")
NO_MODIFY_SUBJECT = _("You can only modify status of your own subjects.")
NO_MODIFY_ACHIEVEMENT = _("You do not have permission to modify achievements.")
NO_MODIFY_READING = _("You do not have permission to modify reading entries.")
NO_MODIFY_CLUB = _("You do not have permission to modify club entries.")

# Lessons
OWN_OFFERINGS_ONLY = _("You can only modify your own offerings.")
NO_VIEW_LESSON = _("You do not have permission to view this lesson.")
NO_TOPICS_FOUND = _("No topics found for this lesson.")
NOT_A_SUBTOPIC = _("This topic is not a subtopic.")

# Resources
CHILD_NOT_FOUND = _("Child not found or not linked to your account.")
STUDENT_NOT_FOUND = _("Student not found.")
CERTIFICATE_NOT_FOUND = _("Certificate file not found.")
NO_CERTIFICATE = _("No certificate file attached to this achievement.")

# Generic
GENERIC_ERROR = _("An error occurred.")
