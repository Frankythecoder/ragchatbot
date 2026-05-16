from django.contrib.auth import views as auth_views
from django.urls import path

from . import views  # noqa: F401 — SignUpView kept for future re-enable

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Public signups are disabled. Create accounts via the Django admin
    # (/admin/ → Users → Add User). To re-enable, uncomment the line below.
    # path("signup/", views.SignUpView.as_view(), name="signup"),
]
