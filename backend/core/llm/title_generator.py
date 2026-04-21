def build_title_conversation(user_message, ai_response):
    """Build a conversation that asks the LLM to generate a short chat title
    from the first user/assistant exchange (ChatGPT-style auto-naming).
    """
    return [
        {
            "role": "system",
            "content": (
                "You generate concise chat titles. "
                "Produce a single title of 3 to 6 words that captures the main topic "
                "of the conversation. Use title case. "
                "Do not use surrounding quotes, emoji, or trailing punctuation. "
                "Return only the title text and nothing else."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User's first message:\n{user_message}\n\n"
                f"Assistant's response:\n{ai_response}\n\n"
                f"Title:"
            ),
        },
    ]
