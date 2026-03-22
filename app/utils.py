import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_client_id() -> str:
    from flask import session
    if "client_id" not in session:
        import uuid
        session["client_id"] = str(uuid.uuid4())
        session.modified = True
    return session["client_id"]


def load_system_prompt() -> str:
    path = Path(config.SYSTEM_PROMPT_PATH)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    return (
        "You are a specialized AI assistant for identifying movies based on vague or incomplete user memories. "
        "Help the user find a movie, TV series, cartoon, or anime based on partial or inaccurate descriptions."
    )


def serialize_chat(chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


def serialize_message(message) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


def get_chat_or_404(chat_id: str):
    from flask import session
    from .models import Chat
    client_id = get_client_id()
    chat = Chat.query.filter_by(id=chat_id, client_id=client_id).first()
    if not chat:
        raise ValueError("Чат не знайдено")
    return chat


def get_chat_messages(chat_id: str):
    from .models import Message
    return (
        Message.query.filter_by(chat_id=chat_id)
        .order_by(Message.id.asc())
        .all()
    )


def suggest_chat_title(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return "Новий чат"
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def extract_high_confidence_title(assistant_text: str) -> str | None:
    patterns = [
        r"^Title:\s*(.+)$"
    ]

    for pattern in patterns:
        match = re.search(pattern, assistant_text, re.MULTILINE)
        if match:
            title = re.sub(r"\s+", " ", match.group(1).strip())
            return title or None

    return None


def build_tmdb_search_url(title: str | None) -> str | None:
    if not title:
        return None
    return f"https://www.themoviedb.org/search?query={quote(title)}"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def safe_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result

    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []

    return []


def deduplicate_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []

    for item in items:
        key = item.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())

    return result