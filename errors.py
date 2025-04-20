ERROR_LIST = []

class Error:
    def __init__(self, error, text, code, error_key):
        self.error = error
        self.text = text
        self.code = code
        self.error_key = error_key

    def return_error(self):
        return {"error": self.error, "text": self.text, "code": self.code}

    def return_text(self):
        return self.text

    def get_error_key(self, error_key):
        return self.error_key == error_key


def register_class(cls):
    ERROR_LIST.append(cls)
    return cls


def find_error_by_key(searched_key):
    for error_cls in ERROR_LIST:
        error_instance = error_cls()
        if searched_key in error_instance.error_key:
            return error_instance.return_text()
    return None


@register_class
class CommonPassword(Error):
    def __init__(self):
        super().__init__(
            error="to_common_password",
            text="Пароль слишком простой",
            code=400,
            error_key=['password1']
        )


@register_class
class PasswordIsNotIdentical(Error):
    def __init__(self):
        super().__init__(
            error="different_password",
            text="Пароль не совподает",
            code=400,
            error_key=['password2']
        )


@register_class
class EmailExists(Error):
    def __init__(self):
        super().__init__(
            error="email_exists",
            text="Адрес электронной почты уже зарегистрирован",
            code=404,
            error_key=['email']
        )
