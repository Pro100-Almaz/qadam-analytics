from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = 'apps.authentication'

    def ready(self):
        import apps.authentication.signals  # noqa: F401 — connects the receivers
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

        # Same reason: the m2m cross-school guard has to be connected in every
        # process, and it deliberately has no sender, so there is no model
        # module that would naturally own it.
        from core.tenancy_guards import register_m2m_guard
        register_m2m_guard()
