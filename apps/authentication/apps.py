from django.apps import apps, AppConfig


class AuthenticationConfig(AppConfig):
    name = 'apps.authentication'

    def ready(self):
        import apps.authentication.signals
        # Tenancy system checks. They span every tenant app, but `core` is not
        # an installed app, so they are registered from the one AppConfig that
        # already has a ready() — importing the module is what registers them.
        import core.checks  # noqa: F401

        # Connect the School uuid<->pk cache invalidation here rather than on
        # import, so it happens in every process — including management
        # commands that never load the URLconf, and so never import whatever
        # calls the lookups.
        from apps.authentication.school_cache import _register_invalidation
        _register_invalidation()
