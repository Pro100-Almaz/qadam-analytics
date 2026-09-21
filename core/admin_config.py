"""The AppConfig that makes `admin.site` our own site.

Separate from `core/admin.py` on purpose. INSTALLED_APPS entries are imported
during `apps.populate()` phase 1, *before* the model registry is ready, and
`core.admin` imports `django.contrib.admin` — the whole package, ModelAdmin and
forms included — which is not safe that early. `django.contrib.admin.apps` is a
submodule precisely so the config can be imported without the package, and
`default_site` is a string precisely so the site is resolved later, in ready().
"""

from django.contrib.admin.apps import AdminConfig


class QadamAdminConfig(AdminConfig):
    """Installed in place of `django.contrib.admin`.

    Swapping the site through `default_site` rather than by instantiating and
    re-registering means every existing `@admin.register(...)` keeps working
    untouched.
    """

    default_site = 'core.admin.QadamAdminSite'
