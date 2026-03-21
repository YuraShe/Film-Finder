let currentChatId = null;

const chatBox = document.getElementById("chat-box");
const chatListDiv = document.getElementById("chat-list");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const chatTitleEl = document.getElementById("current-chat-title");

// При завантаженні сторінки завантажуємо список
document.addEventListener("DOMContentLoaded", loadAllChats);

// 1. Завантаження списку всіх чатів
async function loadAllChats() {
    try {
        const res = await fetch("/chats");
        const data = await res.json();
        
        chatListDiv.innerHTML = "";
        
        if (data.chats) {
            // Перевертаємо, щоб найновіші були зверху
            const reversedChats = data.chats.reverse();
            
            reversedChats.forEach(chat => {
                const div = document.createElement("div");
                div.className = `chat-list-item ${chat.id === currentChatId ? 'active' : ''}`;
                div.innerText = chat.title;
                div.addEventListener('click', () => selectChat(chat.id, chat.title));
                chatListDiv.appendChild(div);
            });

            // 🔹 АВТОМАТИЧНЕ ВІДКРИТТЯ ЧАТУ
            // Якщо жоден чат ще не вибрано (після оновлення сторінки)
            if (!currentChatId) {
                if (reversedChats.length > 0) {
                    // Відкриваємо найновіший існуючий чат
                    selectChat(reversedChats[0].id, reversedChats[0].title);
                } else {
                    // Якщо історія абсолютно порожня, створюємо перший чат
                    createNewChat();
                }
            }
        } else {
            chatListDiv.innerHTML = "<div class='text-muted p-2'>Не вдалося завантажити чати</div>";
        }
    } catch (err) {
        chatListDiv.innerHTML = "<div class='text-muted p-2'>Помилка з'єднання</div>";
    }
}

// 2. Створення нового чату
async function createNewChat() {
    const res = await fetch("/chat/new", { method: "POST" });
    const data = await res.json();
    
    await selectChat(data.id, data.title);
}

// 3. Вибір чату з історії (і завантаження його повідомлень)
async function selectChat(chatId, title) {
    currentChatId = chatId;
    chatTitleEl.innerText = title;
    
    // Розблоковуємо інпут
    userInput.disabled = false;
    sendBtn.disabled = false;
    userInput.focus();

    try {
        // Завантажуємо історію вибраного чату
        const res = await fetch(`/chat/${chatId}`);
        const data = await res.json();
        
        chatBox.innerHTML = "";
        
        if (data.history && data.history.length === 0) {
            appendMessage("assistant", "Привіт! Я слухаю. Про який фільм поговоримо?");
        } else if (data.history) {
            // Відмальовуємо всю попередню історію
            data.history.forEach(msg => appendMessage(msg.role, msg.content));
        } else {
            appendMessage("error", "❌ Помилка: " + (data.error || "Не вдалося завантажити історію"));
        }
    } catch (err) {
        chatBox.innerHTML = "";
        appendMessage("error", "❌ Помилка з'єднання при завантаженні чату.");
    }
    
    loadAllChats(); // Оновлюємо список, щоб підсвітити активний чат
}

// 4. Відправка повідомлення
function handleKeyPress(event) {
    if (event.key === "Enter" && !userInput.disabled) {
        sendMessage();
    }
}

async function sendMessage() {
    if (!currentChatId) return;
    
    const message = userInput.value.trim();
    if (!message) return;

    appendMessage("user", message);
    userInput.value = "";
    
    toggleInputState(true);
    const loadingId = showLoading();

    try {
        const res = await fetch(`/chat/${currentChatId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        });

        const data = await res.json();
        hideLoading(loadingId); 

        if (data.response) {
            appendMessage("assistant", data.response);
            // Якщо назва чату змінилася (після першого повідомлення), оновлюємо
            if (chatTitleEl.innerText === "Новий пошук 🎬" && data.title) {
                chatTitleEl.innerText = data.title;
                loadAllChats(); 
            }
        } else {
            appendMessage("error", "❌ Помилка: " + data.error);
        }
    } catch (err) {
        hideLoading(loadingId);
        appendMessage("error", "❌ Помилка з'єднання.");
    } finally {
        toggleInputState(false);
        userInput.focus();
    }
}

// 5. Видалення поточного чату
async function deleteCurrentChat() {
    

    await fetch(`/chat/${currentChatId}`, { method: "DELETE" });
    
    currentChatId = null;
    chatTitleEl.innerText = "🍿 Завантаження...";
    chatBox.innerHTML = "";
    userInput.disabled = true;
    sendBtn.disabled = true;
    
    // Завантажуємо список наново (він автоматично відкриє наступний доступний чат)
    loadAllChats();
}

// --- Допоміжні функції (UI) ---
function appendMessage(role, text) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.innerText = text;
    chatBox.appendChild(div);
    scrollToBottom();
}

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
    if (loadingDiv) loadingDiv.remove();
}

function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

function toggleInputState(isDisabled) {
    userInput.disabled = isDisabled;
    sendBtn.disabled = isDisabled;
    userInput.placeholder = isDisabled ? "Бот друкує..." : "Напишіть повідомлення...";
}