from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    session,
    stream_with_context,
)
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI

import config


db = SQLAlchemy()
BASE_DIR = Path(__file__).resolve().parent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False

    db.init_app(app)

    return app


app = create_app()

client = OpenAI(
    base_url=config.API_BASE,
    api_key=config.API_KEY,
)


class Chat(db.Model):
    __tablename__ = "chats"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, default="Новий чат")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(
        db.String(36),
        db.ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


def get_client_id() -> str:
    if "client_id" not in session:
        session["client_id"] = str(uuid.uuid4())
        session.modified = True
    return session["client_id"]


def load_system_prompt() -> str:
    path = Path(config.SYSTEM_PROMPT_PATH)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    return "Ти корисний асистент з пошуку фільмів."


def serialize_chat(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


def get_chat_or_404(chat_id: str) -> Chat:
    client_id = get_client_id()
    chat = Chat.query.filter_by(id=chat_id, client_id=client_id).first()
    if not chat:
        raise ValueError("Чат не знайдено")
    return chat


def get_chat_messages(chat_id: str) -> list[Message]:
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
    """
    Даємо Netflix link тільки коли модель дала ВПЕВНЕНИЙ основний варіант
    у форматі:
    Назва:
    Рік:
    Чому це підходить:
    """
    match = re.search(r"^Назва:\s*(.+)$", assistant_text, re.MULTILINE)
    if not match:
        return None

    title = match.group(1).strip()
    title = re.sub(r"\s+", " ", title)
    return title or None


def build_netflix_search_url(title: str | None) -> str | None:
    if not title:
        return None
    return f"https://www.netflix.com/search?q={quote(title)}"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/chats")
def list_chats():
    client_id = get_client_id()
    chats = (
        Chat.query.filter_by(client_id=client_id)
        .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
        .all()
    )
    return jsonify({"chats": [serialize_chat(chat) for chat in chats]})


@app.post("/api/chats")
def create_chat():
    client_id = get_client_id()
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip() or "Новий чат"

    chat = Chat(client_id=client_id, title=title)
    db.session.add(chat)
    db.session.commit()

    return jsonify({"chat": serialize_chat(chat)}), 201


@app.get("/api/chats/<chat_id>/messages")
def get_messages(chat_id: str):
    try:
        chat = get_chat_or_404(chat_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    messages = get_chat_messages(chat.id)
    return jsonify({
        "chat": serialize_chat(chat),
        "messages": [serialize_message(message) for message in messages],
    })


@app.patch("/api/chats/<chat_id>")
def rename_chat(chat_id: str):
    try:
        chat = get_chat_or_404(chat_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    payload = request.get_json(silent=True) or {}
    new_title = (payload.get("title") or "").strip()

    if not new_title:
        return jsonify({"error": "Нова назва чату порожня"}), 400

    chat.title = new_title[:200]
    chat.updated_at = utcnow()
    db.session.commit()

    return jsonify({"chat": serialize_chat(chat)})


@app.delete("/api/chats/<chat_id>")
def delete_chat(chat_id: str):
    try:
        chat = get_chat_or_404(chat_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    Message.query.filter_by(chat_id=chat.id).delete()
    db.session.delete(chat)
    db.session.commit()

    return jsonify({"status": "deleted"})


@app.post("/api/chats/<chat_id>/stream")
def stream_chat(chat_id: str):
    try:
        chat = get_chat_or_404(chat_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Повідомлення порожнє"}), 400

    user_db_message = Message(chat_id=chat.id, role="user", content=user_message)
    db.session.add(user_db_message)

    if chat.title == "Новий чат":
        chat.title = suggest_chat_title(user_message)

    chat.updated_at = utcnow()
    db.session.commit()

    history = get_chat_messages(chat.id)

    messages_for_model = [
        {"role": "system", "content": load_system_prompt()}
    ] + [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]

    @stream_with_context
    def generate():
        assistant_parts: list[str] = []

        yield sse("chat", {"chat": serialize_chat(chat)})
        yield sse("user_message", {"message": serialize_message(user_db_message)})

        try:
            stream = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=messages_for_model,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
                stream=True,
            )

            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue

                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)

                if piece:
                    assistant_parts.append(piece)
                    yield sse("token", {"text": piece})

            assistant_text = "".join(assistant_parts).strip()

            if not assistant_text:
                assistant_text = "Не вдалося згенерувати відповідь."

            assistant_db_message = Message(
                chat_id=chat.id,
                role="assistant",
                content=assistant_text,
            )
            db.session.add(assistant_db_message)
            chat.updated_at = utcnow()
            db.session.commit()

            detected_title = extract_high_confidence_title(assistant_text)
            netflix_url = build_netflix_search_url(detected_title)

            yield sse(
                "done",
                {
                    "chat": serialize_chat(chat),
                    "assistant_message": serialize_message(assistant_db_message),
                    "detected_title": detected_title,
                    "netflix_search_url": netflix_url,
                },
            )

        except Exception as exc:
            db.session.rollback()
            yield sse("error", {"message": str(exc)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)


with app.app_context():
    db.create_all()