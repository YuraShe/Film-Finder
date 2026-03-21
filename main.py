from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
import os
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

client = OpenAI(
    base_url=config.API_BASE,
    api_key=config.API_KEY
)

def get_system_prompt():
    if os.path.exists(config.SYSTEM_PROMPT_PATH):
        with open(config.SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "Ти корисний асистент з пошуку фільмів."

SYSTEM_PROMPT = get_system_prompt()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Повідомлення порожнє"}), 400

    if "history" not in session:
        session["history"] = []

    history = session["history"]

    # Формуємо список повідомлень для API
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_message}]

    try:
        response = client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=messages,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS
        )

        assistant_message = response.choices[0].message.content

        # Оновлюємо історію
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": assistant_message})
        
        # Зберігаємо оновлену історію в сесії Flask
        session["history"] = history
        session.modified = True 

        return jsonify({"response": assistant_message})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/history", methods=["GET"])
def get_history():
    """Повертає історію чату для завантаження на фронтенді"""
    return jsonify({"history": session.get("history", [])})

@app.route("/reset", methods=["POST"])
def reset():
    session.pop("history", None)
    return jsonify({"status": "cleared"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)