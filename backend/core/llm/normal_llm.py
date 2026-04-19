def build_normal_conversation(content, files, history_messages):
    """Build the standard-mode conversation with chat history and attachments.

    history_messages is the already-trimmed list of Message rows for the thread
    (ordered by timestamp, including the current user message as the last item).
    """
    conversation = [
        {"role": "system", "content": "You are a helpful AI assistant."}
    ]

    for msg in history_messages[:-1]:
        role = "user" if msg.sender == "user" else "assistant"
        conversation.append({"role": role, "content": msg.content})

    # Current user message -- may include file content for the LLM
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

    return conversation
