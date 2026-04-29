from django.urls import path

from . import views

app_name = 'auth-api'

urlpatterns = [
    path('login/', views.LoginAPIView.as_view(), name='login'),
    path('register/', views.RegisterAPIView.as_view(), name='register'),
    path('logout/', views.LogoutAPIView.as_view(), name='logout'),
    path('me/', views.CurrentUserAPIView.as_view(), name='current-user'),
    path('me/avatar/', views.AvatarUploadAPIView.as_view(), name='avatar-upload'),
    path('forget-password/', views.ForgetPasswordAPIView.as_view(), name='forget-password'),
    path(
        'verify-code/<str:username>/<str:signed_code>/',
        views.VerificationCodeAPIView.as_view(),
        name='verify-code',
    ),
    path(
        'change-password/<str:username>/<str:signed_code>/',
        views.PasswordChangeAPIView.as_view(),
        name='change-password',
    ),
    path(
        'reset/<str:uidb64>/<str:token>/',
        views.ResetPasswordAPIView.as_view(),
        name='reset-password',
    ),
    path('school-groups/', views.SchoolGroupListAPIView.as_view(), name='school-groups'),
    # path('school-groups/<int:pk>/', views.SchoolGroupDetailAPIView.as_view(), name='school-group-detail'),
]
