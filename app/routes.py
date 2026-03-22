from flask import Blueprint, Response, jsonify, render_template, request, session, stream_with_context
from .config import client

from . import db
from .analyzer import (
    analyze_conversation_for_retrieval,
    build_final_messages,
    should_search_chroma,
    build_chroma_query,
)
from .chroma_utils import search_movies
from .models import Chat, Message
from .utils import (
    get_client_id,
    get_chat_or_404,
    get_chat_messages,
    serialize_chat,
    serialize_message,
    suggest_chat_title,
    extract_high_confidence_title,
    build_tmdb_search_url,
    sse,
    utcnow,
)

from . import config

api_bp = Blueprint('api', __name__)


@api_bp.get("/chats")
def list_chats():
    client_id = get_client_id()
    chats = (
        Chat.query.filter_by(client_id=client_id)
        .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
        .all()
    )
    return jsonify({"chats": [serialize_chat(chat) for chat in chats]})


@api_bp.post("/chats")
def create_chat():
    client_id = get_client_id()
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip() or "Новий чат"

    chat = Chat(client_id=client_id, title=title)
    db.session.add(chat)
    db.session.commit()

    return jsonify({"chat": serialize_chat(chat)}), 201


@api_bp.get("/chats/<chat_id>/messages")
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


@api_bp.patch("/chats/<chat_id>")
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


@api_bp.delete("/chats/<chat_id>")
def delete_chat(chat_id: str):
    try:
        chat = get_chat_or_404(chat_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    Message.query.filter_by(chat_id=chat.id).delete()
    db.session.delete(chat)
    db.session.commit()

    return jsonify({"status": "deleted"})


@api_bp.post("/chats/<chat_id>/stream")
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

    history_for_analyzer = [
        {"role": "user", "content": msg.content}
        for msg in history
        if msg.role == "user" and (msg.content or "").strip()
    ]

    @stream_with_context
    def generate():
        assistant_parts: list[str] = []

        yield sse("chat", {"chat": serialize_chat(chat)})
        yield sse("user_message", {"message": serialize_message(user_db_message)})

        try:
            analysis = analyze_conversation_for_retrieval(history_for_analyzer)

            yield sse(
                "analysis",
                {
                    "need_search": analysis["need_search"],
                    "confidence": analysis["confidence"],
                    "content_type": analysis["content_type"],
                    "keywords": analysis["keywords"],
                    "clarifying_questions": analysis["clarifying_questions"],
                },
            )

            candidates: list[dict] = []
            query_for_chroma = ""

            if should_search_chroma(analysis, history):
                query_for_chroma = build_chroma_query(analysis)
                candidates = search_movies(
                    user_query=query_for_chroma,
                    n_results=config.RETRIEVAL_TOP_K,
                )

                yield sse(
                    "retrieval",
                    {
                        "used": True,
                        "query": query_for_chroma,
                        "hits_count": len(candidates),
                        "titles": [c["title"] for c in candidates],
                    },
                )
            else:
                yield sse(
                    "retrieval",
                    {
                        "used": False,
                        "query": "",
                        "hits_count": 0,
                        "titles": [],
                    },
                )

            final_messages = build_final_messages(
                history=history,
                analysis=analysis,
                candidates=candidates,
            )

            stream = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=final_messages,
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
            netflix_url = build_tmdb_search_url(detected_title)

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