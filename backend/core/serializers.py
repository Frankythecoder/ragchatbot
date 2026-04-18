from rest_framework import serializers
from .models import ChatThread, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "sender", "content", "sources", "retrieved_chunks", "tokens", "attachments", "timestamp"]


class ChatThreadSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatThread
        fields = ["id", "title", "created_at", "updated_at", "message_count"]

    def get_message_count(self, obj):
        return obj.messages.count()


class ChatThreadDetailSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatThread
        fields = ["id", "title", "created_at", "updated_at", "messages"]
