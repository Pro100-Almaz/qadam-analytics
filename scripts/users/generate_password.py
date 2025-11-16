import secrets
import string

def generate_password(length = 15):
    chars = string.ascii_letters + string.digits+ string.punctuation
    return ''.join(secrets.choice(chars) for i in range(length))
