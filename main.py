import json
import os
import uuid
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import config

app = Flask(__name__)

client = OpenAI(
    base_url=config.API_BASE,
    api_key=config.API_KEY
)

CHATS_FILE = "chats.json"

# --- Допоміжні функції для роботи з JSON ---
def load_chats():
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_chats(chats):
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False, indent=4)

def get_system_prompt():
    if os.path.exists(config.SYSTEM_PROMPT_PATH):
        with open(config.SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "Ти корисний асистент з пошуку фільмів."

SYSTEM_PROMPT = get_system_prompt()

# --- Маршрути ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chats", methods=["GET"])
def get_all_chats():
    """Повертає список всіх чатів для бічної панелі"""
    chats = load_chats()
    # Повертаємо лише ID та назви
    chat_list = [{"id": k, "title": v["title"]} for k, v in chats.items()]
    return jsonify({"chats": chat_list})

@app.route("/chat/<chat_id>", methods=["GET"])
def get_chat(chat_id):
    """Повертає історію конкретного чату"""
    chats = load_chats()
    if chat_id in chats:
        return jsonify({"history": chats[chat_id]["messages"]})
    return jsonify({"error": "Чат не знайдено"}), 404

@app.route("/chat/new", methods=["POST"])
def create_chat():
    """Створює новий порожній чат"""
    chats = load_chats()
    chat_id = str(uuid.uuid4())
    chats[chat_id] = {
        "title": "Новий пошук 🎬",
        "messages": []
    }
    save_chats(chats)
    return jsonify({"id": chat_id, "title": chats[chat_id]["title"]})

@app.route("/chat/<chat_id>", methods=["POST"])
def send_message(chat_id):
    """Обробляє нове повідомлення в конкретному чаті"""
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Повідомлення порожнє"}), 400

    chats = load_chats()
    if chat_id not in chats:
        return jsonify({"error": "Чат не знайдено"}), 404

    chat_data = chats[chat_id]
    
    # Якщо це перше повідомлення, генеруємо назву чату з нього
    if len(chat_data["messages"]) == 0:
        chat_data["title"] = user_message[:20] + "..." if len(user_message) > 20 else user_message

    messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_data["messages"] + [{"role": "user", "content": user_message}]

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=messages_for_api,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS
        )

        assistant_message = response.choices[0].message.content

        # Зберігаємо повідомлення
        chat_data["messages"].append({"role": "user", "content": user_message})
        chat_data["messages"].append({"role": "assistant", "content": assistant_message})
        
        save_chats(chats)

        return jsonify({
            "response": assistant_message,
            "title": chat_data["title"] # Повертаємо назву, якщо вона оновилася
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chat/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    chats = load_chats()
    if chat_id in chats:
        del chats[chat_id]
        save_chats(chats)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404

if __name__ == "__main__":
    app.run(debug=True, port=5000)