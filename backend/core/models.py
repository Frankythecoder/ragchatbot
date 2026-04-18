from django.db import models
from django.contrib.auth.models import User


class ChatThread(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="threads")
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} ({self.user.username})"


class Message(models.Model):
    SENDER_CHOICES = [("user", "User"), ("ai", "AI")]

    thread = models.ForeignKey(
        ChatThread, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    retrieved_chunks = models.JSONField(default=list, blank=True)
    tokens = models.JSONField(default=None, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.sender}: {self.content[:50]}"
