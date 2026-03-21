document.addEventListener("DOMContentLoaded", loadHistory);

const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");

// Завантаження історії при відкритті сторінки
async function loadHistory() {
    try {
        const res = await fetch("/history");
        const data = await res.json();
        
        if (data.history && data.history.length > 0) {
            data.history.forEach(msg => {
                appendMessage(msg.role, msg.content);
            });
        }
    } catch (err) {
        console.error("Помилка завантаження історії:", err);
    }
}

// Обробка натискання клавіші Enter
function handleKeyPress(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
}

async function sendMessage() {
    const message = userInput.value.trim();
    if (!message) return;

    // 1. Показуємо повідомлення користувача
    appendMessage("user", message);
    userInput.value = "";
    
    // 2. Показуємо анімацію загрузки
    const loadingId = showLoading();

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });

        const data = await res.json();
        
        // 3. Ховаємо анімацію
        hideLoading(loadingId); 

        if (data.response) {
            appendMessage("assistant", data.response);
        } else {
            appendMessage("error", "❌ Помилка: " + data.error);
        }
    } catch (err) {
        hideLoading(loadingId);
        appendMessage("error", "❌ Немає з'єднання з сервером.");
    }
}

function appendMessage(role, text) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerText = text;
    chatBox.appendChild(div);
    scrollToBottom();
}

// Функції для анімації "друку"
function showLoading() {
    const id = "loading-" + Date.now();
    const loadingDiv = document.createElement("div");
    loadingDiv.className = "typing-indicator";
    loadingDiv.id = id;
    loadingDiv.innerHTML = `<div class="dot"></div><div class="dot"></div><div class="dot"></div>`;
    
    chatBox.appendChild(loadingDiv);
    scrollToBottom();
    return id;
}

function hideLoading(id) {
    const loadingDiv = document.getElementById(id);
    if (loadingDiv) {
        loadingDiv.remove();
    }
}

function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Функція для скидання чату
async function resetChat() {
    await fetch("/reset", { method: "POST" });
    chatBox.innerHTML = "";
}