from django.urls import path
from django.contrib.auth import views as auth_views
from .views import ProfileView, LogoutView, SessionManagementView, AlertsView, AlertActionView, AlertPreferencesView

app_name = "accounts"

urlpatterns = [
    path("profile/", ProfileView.as_view(template_name="accounts/profile.html"), name="profile"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('sessions/', SessionManagementView.as_view(), name='sessions'),
    path('alerts/', AlertsView.as_view(), name='alerts'),
    path('alerts/<int:alert_id>/', AlertActionView.as_view(), name='alert_action'),
    path('alert-preferences/', AlertPreferencesView.as_view(), name='alert_preferences'),
]