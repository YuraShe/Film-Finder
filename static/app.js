let currentChatId = null;
let isStreaming = false;

const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const chatTitleEl = document.getElementById("chat-title");
const extraPanelEl = document.getElementById("extra-panel");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("user-input");
const sendBtnEl = document.getElementById("send-btn");

document.getElementById("new-chat-btn").addEventListener("click", handleCreateChat);
document.getElementById("rename-chat-btn").addEventListener("click", renameCurrentChat);
document.getElementById("delete-chat-btn").addEventListener("click", deleteCurrentChat);
formEl.addEventListener("submit", handleSendMessage);

inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        formEl.requestSubmit();
    }
});

inputEl.addEventListener("input", autoResizeTextarea);

document.addEventListener("DOMContentLoaded", async () => {
    await bootstrap();
});

async function bootstrap() {
    const chats = await fetchChats();

    if (!chats.length) {
        const created = await createChat();
        await openChat(created.id);
        return;
    }

    await openChat(chats[0].id);
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });

    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            if (data.error) message = data.error;
        } catch (_) {}
        throw new Error(message);
    }

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
        return response.json();
    }

    return response;
}

async function fetchChats() {
    const data = await api("/api/chats");
    renderChatList(data.chats);
    return data.chats;
}

async function createChat() {
    const data = await api("/api/chats", {
        method: "POST",
        body: JSON.stringify({}),
    });

    await fetchChats();
    return data.chat;
}

async function openChat(chatId) {
    currentChatId = chatId;
    const data = await api(`/api/chats/${chatId}/messages`);
    chatTitleEl.textContent = data.chat.title;
    renderMessages(data.messages);
    await fetchChats();
}

async function handleCreateChat() {
    if (isStreaming) return;
    const chat = await createChat();
    await openChat(chat.id);
    inputEl.focus();
}

async function renameCurrentChat() {
    if (!currentChatId || isStreaming) return;

    const currentTitle = chatTitleEl.textContent.trim();
    const newTitle = window.prompt("Нова назва чату:", currentTitle);

    if (!newTitle || !newTitle.trim()) return;

    const data = await api(`/api/chats/${currentChatId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: newTitle.trim() }),
    });

    chatTitleEl.textContent = data.chat.title;
    await fetchChats();
}

async function deleteCurrentChat() {
    if (!currentChatId || isStreaming) return;

    const ok = window.confirm("Точно видалити цей чат?");
    if (!ok) return;

    await api(`/api/chats/${currentChatId}`, { method: "DELETE" });

    const chats = await fetchChats();
    if (chats.length) {
        await openChat(chats[0].id);
    } else {
        const chat = await createChat();
        await openChat(chat.id);
    }
}

async function handleSendMessage(event) {
    event.preventDefault();

    const text = inputEl.value.trim();
    if (!text || isStreaming) return;

    if (!currentChatId) {
        const chat = await createChat();
        currentChatId = chat.id;
    }

    inputEl.value = "";
    autoResizeTextarea();
    hideExtraPanel();

    appendMessage("user", text);

    const assistantBubble = appendMessage("assistant", "", true);
    const assistantContentEl = assistantBubble.querySelector(".message-content");

    lockComposer(true);
    isStreaming = true;

    try {
        const response = await fetch(`/api/chats/${currentChatId}/stream`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ message: text }),
        });

        if (!response.ok || !response.body) {
            let msg = `HTTP ${response.status}`;
            try {
                const data = await response.json();
                if (data.error) msg = data.error;
            } catch (_) {}
            throw new Error(msg);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            buffer = processSSEBuffer(buffer, {
                onToken(textPiece) {
                    assistantContentEl.textContent += textPiece;
                    scrollMessagesToBottom();
                },
                onDone(payload) {
                    assistantBubble.classList.remove("typing");

                    if (payload.chat) {
                        chatTitleEl.textContent = payload.chat.title;
                    }

                    if (payload.netflix_search_url && payload.detected_title) {
                        showNetflixCard(payload.detected_title, payload.netflix_search_url);
                    }

                    fetchChats();
                },
                onError(payload) {
                    assistantContentEl.textContent = `Помилка: ${payload.message || "Невідома помилка"}`;
                    assistantBubble.classList.remove("typing");
                    assistantBubble.classList.add("error");
                },
            });
        }
    } catch (error) {
        assistantContentEl.textContent = `Помилка: ${error.message}`;
        assistantBubble.classList.remove("typing");
        assistantBubble.classList.add("error");
    } finally {
        isStreaming = false;
        lockComposer(false);
        scrollMessagesToBottom();
    }
}

function processSSEBuffer(buffer, handlers) {
    const events = buffer.split("\n\n");
    const incomplete = events.pop();

    for (const rawEvent of events) {
        if (!rawEvent.trim()) continue;

        const lines = rawEvent.split("\n");
        let eventName = "message";
        let dataRaw = "";

        for (const line of lines) {
            if (line.startsWith("event:")) {
                eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
                dataRaw += line.slice(5).trim();
            }
        }

        let payload = {};
        try {
            payload = JSON.parse(dataRaw || "{}");
        } catch (_) {}

        if (eventName === "token") {
            handlers.onToken?.(payload.text || "");
        } else if (eventName === "done") {
            handlers.onDone?.(payload);
        } else if (eventName === "error") {
            handlers.onError?.(payload);
        } else if (eventName === "chat") {
            if (payload.chat?.title) {
                chatTitleEl.textContent = payload.chat.title;
            }
        }
    }

    return incomplete || "";
}

function renderChatList(chats) {
    chatListEl.innerHTML = "";

    if (!chats.length) {
        chatListEl.innerHTML = `
            <div class="chat-item">
                <div class="chat-item-title">Немає чатів</div>
                <div class="chat-item-meta">Створи перший чат</div>
            </div>
        `;
        return;
    }

    for (const chat of chats) {
        const btn = document.createElement("button");
        btn.className = `chat-item ${chat.id === currentChatId ? "active" : ""}`;
        btn.innerHTML = `
            <div class="chat-item-title">${escapeHtml(chat.title)}</div>
            <div class="chat-item-meta">${formatDate(chat.updated_at)}</div>
        `;
        btn.addEventListener("click", () => openChat(chat.id));
        chatListEl.appendChild(btn);
    }
}

function renderMessages(messages) {
    messagesEl.innerHTML = "";

    if (!messages.length) {
        messagesEl.innerHTML = `
            <div class="empty-state">
                <h2>Знайдемо твій фільм</h2>
                <p>
                    Напиши все, що пам’ятаєш: сцену, героя, приблизний рік,
                    країну, атмосферу, кінець чи дивний момент з сюжету.
                </p>
            </div>
        `;
        return;
    }

    for (const message of messages) {
        appendMessage(message.role, message.content, false, false);
    }

    scrollMessagesToBottom();
}

function appendMessage(role, text, typing = false, autoScroll = true) {
    if (messagesEl.querySelector(".empty-state")) {
        messagesEl.innerHTML = "";
    }

    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = `message-bubble ${typing ? "typing" : ""}`;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = role === "user" ? "Ти" : "AI";

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = text;

    bubble.appendChild(meta);
    bubble.appendChild(content);
    row.appendChild(bubble);
    messagesEl.appendChild(row);

    if (autoScroll) {
        scrollMessagesToBottom();
    }

    return bubble;
}

function showNetflixCard(title, url) {
    extraPanelEl.classList.remove("hidden");
    extraPanelEl.innerHTML = `
        <div class="netflix-card">
            <div>
                <div class="netflix-card-title">Можливо, це: ${escapeHtml(title)}</div>
                <div class="netflix-card-subtitle">
                    Відкриваємо пошук Netflix по назві
                </div>
            </div>
            <a class="link-btn" href="${url}" target="_blank" rel="noopener noreferrer">
                Відкрити в Netflix
            </a>
        </div>
    `;
}

function hideExtraPanel() {
    extraPanelEl.classList.add("hidden");
    extraPanelEl.innerHTML = "";
}

function lockComposer(locked) {
    inputEl.disabled = locked;
    sendBtnEl.disabled = locked;
    sendBtnEl.textContent = locked ? "Друкує..." : "Надіслати";
}

function scrollMessagesToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function autoResizeTextarea() {
    inputEl.style.height = "auto";
    inputEl.style.height = `${Math.min(inputEl.scrollHeight, 220)}px`;
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatDate(isoDate) {
    const date = new Date(isoDate);
    return date.toLocaleString("uk-UA", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}