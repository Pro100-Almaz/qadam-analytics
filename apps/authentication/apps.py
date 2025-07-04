from django.apps import apps, AppConfig


class AuthenticationConfig(AppConfig):
    name = 'apps.authentication'

    def ready(self):
        import apps.authentication.signals