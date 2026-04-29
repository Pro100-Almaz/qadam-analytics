from django.urls import path

from . import views

app_name = 'notification-api'

urlpatterns = [
    path('', views.NotificationListAPIView.as_view(), name='notification-list'),
    path('count/', views.NotificationCountAPIView.as_view(), name='notification-count'),
    path('<int:pk>/', views.NotificationDetailAPIView.as_view(), name='notification-detail'),
    path('<int:pk>/delete/', views.NotificationDeleteAPIView.as_view(), name='notification-delete'),
]
