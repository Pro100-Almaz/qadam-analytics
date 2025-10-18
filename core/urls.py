from django.contrib import admin
from django.conf import settings
from django.http import HttpResponse
from django.urls import path, include  # add this
from django.conf.urls.static import static
from apps.home.views import main_page


urlpatterns = [
    path("", main_page),
    path('admin/', admin.site.urls),  # Django admin route
    path("", include("apps.authentication.urls")),  # Auth routes - login / register
    path("pages/", include("apps.home.urls")),      # UI Kits Html files
    path("lessons/", include("apps.lesson.urls")), # Lesson app routes
    path("notifications/", include("apps.notification.urls")), #notifications
    path("healthz", lambda r: HttpResponse("ok"), name="healthz"),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
