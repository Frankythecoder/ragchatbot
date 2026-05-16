from django.contrib import admin
from django.urls import path, include

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("core.auth_urls")),
    path("", core_views.chat_view, name="chat"),
    path("api/", include("core.urls")),
]
