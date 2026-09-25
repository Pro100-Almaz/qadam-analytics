from django.contrib import admin
from django.conf import settings
from django.http import HttpResponse
from django.urls import path, include
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from apps.home.admin_views import bulk_enroll_view


urlpatterns = [
    # API v1
    path("api/v1/auth/", include("apps.authentication.api.urls")),
    path("api/v1/", include("apps.home.api.urls")),
    path("api/v1/", include("apps.lesson.api.urls")),
    path("api/v1/notifications/", include("apps.notification.api.urls")),
    path("api/v1/", include("apps.achievement.api.urls")),
    path("api/v1/", include("apps.student_report.api.urls")),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Django admin (session-authenticated; used by superusers)
    path('admin/bulk-enroll/', bulk_enroll_view, name='admin_bulk_enroll_form'),
    path('admin/', admin.site.urls),
    path("healthz", lambda r: HttpResponse("ok"), name="healthz"),

    # The legacy server-rendered views (apps/*/views.py, apps/home/repo/*) are
    # deliberately NOT routed. They were unauthenticated in places — notably
    # /register/, which accepted role=Admin from anonymous users — and are
    # superseded by the DRF API above. The modules remain on disk for
    # reference; re-adding the includes below would make them live again.
    #   path("", main_page),
    #   path("", include("apps.authentication.urls")),
    #   path("pages/", include("apps.home.urls")),
    #   path("lessons/", include("apps.lesson.urls")),
    #   path("notifications/", include("apps.notification.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
