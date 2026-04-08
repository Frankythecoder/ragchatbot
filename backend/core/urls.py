from django.urls import path
from . import views

urlpatterns = [
    path("threads/", views.thread_list, name="thread-list"),
    path("threads/<int:thread_id>/", views.thread_detail, name="thread-detail"),
    path(
        "threads/<int:thread_id>/chat/", views.send_message, name="send-message"
    ),
]
