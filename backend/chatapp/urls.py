from django.contrib import admin
from django.urls import path, include

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("core.auth_urls")),
    path("auth-complete/", core_views.auth_complete, name="auth-complete"),
    path("api/", include("core.urls")),
]
