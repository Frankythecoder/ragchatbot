import os
import tempfile

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from openai import OpenAI

from .models import ChatThread, Message
from .serializers import (
    ChatThreadSerializer,
    ChatThreadDetailSerializer,
    MessageSerializer,
)
from .llm.title_generator import build_title_conversation

# rag_pipeline pulls in faiss + sentence-transformers + torch (~300-400 MB).
# Imported lazily so the chat UI can boot on Render's 512 MB free tier without
# OOM-killing the worker.

User = get_user_model()

client = None


def get_openai_client():
    global client
    if client is None:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return client


def _autotitle_thread(thread, user_content, files, ai_content):
    """Generate and apply a ChatGPT-style short title for a thread's first
    exchange. Falls back to a truncation-based title on any failure.
    """
    user_text = user_content or (files[0].get("name", "") if files else "")
    try:
        ai_client = get_openai_client()
        response = ai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=build_title_conversation(user_text, ai_content),
            max_tokens=24,
        )
        title = response.choices[0].message.content.strip()
        title = title.strip('"').strip("'").strip()
        if title:
            thread.title = title[:60]
            return
    except Exception:
        pass
    # Fallback: truncation-based title
    fallback = user_text or "New Chat"
    thread.title = fallback[:50] + ("..." if len(fallback) > 50 else "")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class SignUpForm(UserCreationForm):
    """Django's built-in UserCreationForm extended with a required email."""

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email already registered.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("login")


@login_required
def chat_view(request):
    """Render the single-page chat UI. Session-authenticated; unauthenticated
    visitors are redirected to /accounts/login/ by @login_required.
    """
    return render(request, "chat.html", {
        "is_superuser": request.user.is_superuser,
        "daily_message_limit": settings.DAILY_MESSAGE_LIMIT,
    })


# ---------------------------------------------------------------------------
# Chat Threads
# ---------------------------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def thread_list(request):
    if request.method == "GET":
        threads = ChatThread.objects.filter(user=request.user)
        serializer = ChatThreadSerializer(threads, many=True)
        return Response(serializer.data)

    # POST — create new thread
    thread = ChatThread.objects.create(user=request.user)
    serializer = ChatThreadSerializer(thread)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def thread_detail(request, thread_id):
    try:
        thread = ChatThread.objects.get(id=thread_id, user=request.user)
    except ChatThread.DoesNotExist:
        return Response(
            {"detail": "Thread not found."}, status=status.HTTP_404_NOT_FOUND
        )

    if request.method == "GET":
        serializer = ChatThreadDetailSerializer(thread)
        return Response(serializer.data)

    if request.method == "PATCH":
        title = request.data.get("title")
        if title:
            thread.title = title[:255]
            thread.save()
        serializer = ChatThreadSerializer(thread)
        return Response(serializer.data)

    # DELETE
    thread.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Chat Messages / AI
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_message(request, thread_id):
    try:
        thread = ChatThread.objects.get(id=thread_id, user=request.user)
    except ChatThread.DoesNotExist:
        return Response(
            {"detail": "Thread not found."}, status=status.HTTP_404_NOT_FOUND
        )

    content = request.data.get("message", "").strip()
    files = request.data.get("files", []) or []

    if not content:
        return Response(
            {"detail": "Message cannot be empty."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Daily rate limit for non-superuser accounts (calendar day, server tz).
    if not request.user.is_superuser:
        today = timezone.now().date()
        daily_count = Message.objects.filter(
            thread__user=request.user,
            sender="user",
            timestamp__date=today,
        ).count()
        if daily_count >= settings.DAILY_MESSAGE_LIMIT:
            return Response(
                {
                    "detail": (
                        f"Daily limit of {settings.DAILY_MESSAGE_LIMIT} "
                        f"messages reached. Please try again tomorrow."
                    )
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

    # Save user message with attachment metadata
    file_meta = [
        {
            "name": f.get("name", "file"),
            "type": f.get("type", "other"),
            "size": f.get("size"),
        }
        for f in files
    ]
    Message.objects.create(
        thread=thread, sender="user", content=content,
        attachments=file_meta,
    )

    # Track first-message state; the ChatGPT-style auto-title is generated
    # after the AI response is known, so the title reflects the conversation.
    user_msg_count = thread.messages.filter(sender="user").count()
    is_first_message = user_msg_count == 1

    # Build RAG conversation from retrieved chunks. Non-superusers query the
    # primary superuser's knowledge base since they cannot upload their own.
    sources = []
    retrieved_chunks = []
    from .llm.rag_pipeline import retrieve, build_rag_conversation
    if request.user.is_superuser:
        rag_user_id = request.user.id
    else:
        admin = User.objects.filter(is_superuser=True).order_by("id").first()
        rag_user_id = admin.id if admin else None
    results = retrieve(rag_user_id, content) if rag_user_id is not None else []
    if results:
        conversation, sources, retrieved_chunks = build_rag_conversation(
            content, results
        )
    else:
        # No documents indexed at all
        ai_content = "I don't know. No documents have been uploaded yet."
        if is_first_message:
            _autotitle_thread(thread, content, files, ai_content)
        Message.objects.create(thread=thread, sender="ai", content=ai_content)
        thread.save()
        return Response(
            {
                "message": ai_content,
                "tokens": None,
                "thread_title": thread.title,
                "sources": [],
                "retrieved_chunks": [],
            }
        )

    # Debug: print what we're sending to OpenAI
    print(f"\n{'='*60}")
    print(f"MESSAGES COUNT: {len(conversation)}")
    for i, msg in enumerate(conversation):
        role = msg["role"]
        text = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
        print(f"  [{i}] {role}: {text[:200]}...")
    print(f"{'='*60}\n")

    # Call OpenAI
    tokens_used = None
    try:
        ai_client = get_openai_client()
        response = ai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=conversation,
        )
        ai_content = response.choices[0].message.content
        tokens_used = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    except Exception as e:
        ai_content = f"I'm sorry, I encountered an error: {str(e)}"

    # If the LLM determined the docs aren't relevant, strip sources/chunks
    if ai_content.lower().startswith("i don't know"):
        sources = []
        retrieved_chunks = []

    # ChatGPT-style auto-title after the first exchange
    if is_first_message:
        _autotitle_thread(thread, content, files, ai_content)

    # Save AI response
    Message.objects.create(
        thread=thread, sender="ai", content=ai_content,
        sources=sources, retrieved_chunks=retrieved_chunks,
        tokens=tokens_used,
    )
    thread.save()  # bumps updated_at

    return Response(
        {
            "message": ai_content,
            "tokens": tokens_used,
            "thread_title": thread.title,
            "sources": sources,
            "retrieved_chunks": retrieved_chunks,
        }
    )


# ---------------------------------------------------------------------------
# Document Upload (RAG)
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_document(request):
    if not request.user.is_superuser:
        return Response(
            {"detail": "Only administrators can upload documents."},
            status=status.HTTP_403_FORBIDDEN,
        )

    file = request.FILES.get("file")
    if not file:
        return Response(
            {"detail": "No file provided."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    filename = file.name.lower()
    supported = (".pdf", ".txt", ".docx", ".pptx", ".xlsx")
    if not any(filename.endswith(ext) for ext in supported):
        return Response(
            {"detail": "Supported formats: PDF, TXT, DOCX, PPTX, XLSX."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from .llm.rag_pipeline import extract_text, index_document

    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        text = extract_text(tmp_path)
        if not text.strip():
            return Response(
                {"detail": "Could not extract text from file."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        file_path = request.data.get("file_path", file.name)
        chunks_added = index_document(request.user.id, file_path, text)
    finally:
        os.unlink(tmp_path)

    return Response({
        "success": True,
        "filename": file.name,
        "chunks_indexed": chunks_added,
    })
