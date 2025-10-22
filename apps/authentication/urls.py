from django.urls import path
from .views import login_view, register_user, custom_logout_view, forget_password_view, send_email_password_change, \
    verification_code_check, password_change_final, reset_password_view

app_name = 'authentication'

urlpatterns = [
    path('login/', login_view, name="login"),
    path('register/', register_user, name="register"),
    path("logout/", custom_logout_view, name="logout"),
    path("reset/<uidb64>/<token>/", reset_password_view, name="reset_password"),
    path("forget_pass_confirm/", forget_password_view, name="forget_password_confirmation"),
    path("validate/<str:username>/<str:signed_code>/", verification_code_check , name="verification_code"),
    path("password_change/<str:username>/<str:signed_code>/pass_change/", password_change_final , name="password_change"),
]
