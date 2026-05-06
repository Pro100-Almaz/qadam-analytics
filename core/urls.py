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
from apps.home.views import main_page
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

    # Existing routes (kept during dual-mode transition)
    path("", main_page),
    path('admin/bulk-enroll/', bulk_enroll_view, name='admin_bulk_enroll_form'),
    path('admin/', admin.site.urls),
    path("", include("apps.authentication.urls")),
    path("pages/", include("apps.home.urls")),
    path("lessons/", include("apps.lesson.urls")),
    path("notifications/", include("apps.notification.urls")),
    path("healthz", lambda r: HttpResponse("ok"), name="healthz"),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
