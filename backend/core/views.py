import os
import tempfile

from django.contrib.auth.models import User
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from openai import OpenAI

from .models import ChatThread, Message
from .serializers import (
    ChatThreadSerializer,
    ChatThreadDetailSerializer,
    MessageSerializer,
)
from .rag import extract_text, index_document, retrieve

client = None


def get_openai_client():
    global client
    if client is None:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return client


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get("username", "").strip()
    email = request.data.get("email", "").strip()
    password = request.data.get("password", "")

    if not all([username, email, password]):
        return Response(
            {"detail": "All fields are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 6:
        return Response(
            {"detail": "Password must be at least 6 characters."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(email=email).exists():
        return Response(
            {"detail": "Email already registered."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {"detail": "Username already taken."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    User.objects.create_user(username=username, email=email, password=password)
    return Response(
        {"success": True, "message": "Account created successfully!"},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    email = request.data.get("email", "").strip()
    password = request.data.get("password", "")

    if not email or not password:
        return Response(
            {"detail": "Email and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {"detail": "Invalid credentials."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.check_password(password):
        return Response(
            {"detail": "Invalid credentials."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "success": True,
            "message": "Login successful",
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return Response(
            {"detail": "Refresh token is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({"success": True, "message": "Logged out successfully."})
    except Exception:
        return Response(
            {"detail": "Invalid or expired token."},
            status=status.HTTP_400_BAD_REQUEST,
        )


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
    mode = request.data.get("mode", "normal")

    if not content and not files:
        return Response(
            {"detail": "Message cannot be empty."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Save user message (text only for DB)
    Message.objects.create(
        thread=thread, sender="user", content=content or "[Files attached]"
    )

    # Auto-title on first user message
    user_msg_count = thread.messages.filter(sender="user").count()
    if user_msg_count == 1:
        title_src = content if content else (
            files[0].get("name", "New Chat") if files else "New Chat"
        )
        thread.title = title_src[:50] + ("..." if len(title_src) > 50 else "")
        thread.save()

    # Build conversation history for LLM (token optimization)
    all_messages = list(thread.messages.order_by("timestamp"))
    max_msgs = settings.MAX_HISTORY_MESSAGES
    if len(all_messages) > max_msgs:
        all_messages = all_messages[-max_msgs:]

    # Build system prompt — RAG or normal
    sources = []
    if mode == "rag" and content:
        results = retrieve(request.user.id, content)
        if results:
            context_text = "\n\n---\n\n".join(r["text"] for r in results)
            sources = list(dict.fromkeys(r["filename"] for r in results))
            system_content = (
                "Answer ONLY using the context below. "
                "If the answer is not found in the context, say 'I don't know.'\n\n"
                f"Context:\n{context_text}"
            )
        else:
            system_content = (
                "No documents have been indexed yet. "
                "Tell the user to upload documents first for RAG mode."
            )
    else:
        system_content = "You are a helpful AI assistant."

    conversation = [{"role": "system", "content": system_content}]

    # Previous messages as plain text
    for msg in all_messages[:-1]:
        role = "user" if msg.sender == "user" else "assistant"
        conversation.append({"role": role, "content": msg.content})

    # Current user message — may include file content for the LLM
    if files:
        user_parts = []
        if content:
            user_parts.append({"type": "text", "text": content})
        for f in files:
            if f.get("type") == "image" and f.get("dataUrl"):
                user_parts.append(
                    {"type": "image_url", "image_url": {"url": f["dataUrl"]}}
                )
            elif f.get("textContent"):
                user_parts.append(
                    {
                        "type": "text",
                        "text": (
                            f"--- File: {f['name']} ---\n"
                            f"{f['textContent']}\n"
                            f"--- End of {f['name']} ---"
                        ),
                    }
                )
            else:
                user_parts.append(
                    {
                        "type": "text",
                        "text": f"[Attached file: {f['name']} ({f.get('type', 'unknown')} file)]",
                    }
                )
        conversation.append({"role": "user", "content": user_parts})
    else:
        conversation.append({"role": "user", "content": content})

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

    # Save AI response
    Message.objects.create(thread=thread, sender="ai", content=ai_content)
    thread.save()  # bumps updated_at

    return Response(
        {
            "message": ai_content,
            "tokens": tokens_used,
            "thread_title": thread.title,
            "sources": sources,
        }
    )


# ---------------------------------------------------------------------------
# Document Upload (RAG)
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_document(request):
    file = request.FILES.get("file")
    if not file:
        return Response(
            {"detail": "No file provided."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    filename = file.name.lower()
    if not (filename.endswith(".pdf") or filename.endswith(".txt")):
        return Response(
            {"detail": "Only PDF and TXT files are supported."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    suffix = ".pdf" if filename.endswith(".pdf") else ".txt"
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
        chunks_added = index_document(request.user.id, file.name, text)
    finally:
        os.unlink(tmp_path)

    return Response({
        "success": True,
        "filename": file.name,
        "chunks_indexed": chunks_added,
    })
