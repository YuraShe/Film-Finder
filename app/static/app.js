let currentChatId = null;
let isStreaming = false;

const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const chatTitleEl = document.getElementById("chat-title");
const extraPanelEl = document.getElementById("extra-panel");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("user-input");
const sendBtnEl = document.getElementById("send-btn");

// Process Server-Sent Events buffer
function processSSEBuffer(buffer, callbacks) {
    const lines = buffer.split('\n');
    let event = null;
    let data = '';

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();

        if (line.startsWith('event:')) {
            event = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
            data = line.substring(5).trim();
        } else if (line === '') {
            // End of event
            if (event && data) {
                try {
                    const payload = JSON.parse(data);

                    switch (event) {
                        case 'token':
                            if (callbacks.onToken && payload.text) {
                                callbacks.onToken(payload.text);
                            }
                            break;
                        case 'done':
                            if (callbacks.onDone) {
                                callbacks.onDone(payload);
                            }
                            break;
                        case 'error':
                            if (callbacks.onError) {
                                callbacks.onError(payload);
                            }
                            break;
                        // Handle other events if needed
                        case 'chat':
                        case 'user_message':
                        case 'analysis':
                        case 'retrieval':
                            // These events don't need specific handling in the buffer processor
                            break;
                    }
                } catch (e) {
                    console.error('Failed to parse SSE data:', data, e);
                }
            }

            event = null;
            data = '';
        }
    }

    // Return any remaining incomplete data
    const lastLine = lines[lines.length - 1];
    if (lastLine && !lastLine.startsWith('event:') && !lastLine.startsWith('data:') && lastLine !== '') {
        return lastLine;
    }

    return '';
}

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
        } catch (_) { }
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
    hideExtraPanel();
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
    const newTitle = window.prompt("New chat title:", currentTitle);

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

    const ok = window.confirm("Are you sure you want to delete this chat?");
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
            } catch (_) { }
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
                    assistantContentEl.textContent = `Error: ${payload.message || "Unknown error"}`;
                    assistantBubble.classList.remove("typing");
                    assistantBubble.classList.add("error");
                },
            });
        }
    } catch (error) {
        assistantContentEl.textContent = `Error: ${error.message}`;
        assistantBubble.classList.remove("typing");
        assistantBubble.classList.add("error");
    } finally {
        isStreaming = false;
        lockComposer(false);
        scrollMessagesToBottom();
    }
}

function renderChatList(chats) {
    chatListEl.innerHTML = "";

    if (!chats.length) {
        chatListEl.innerHTML = `
            <div class="chat-item">
                <div class="chat-item-title">No chats</div>
                <div class="chat-item-meta">Create your first chat</div>
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
                <h2>Let's find your movie</h2>
                <p>
                    Write everything you remember: a scene, a character, approximate year,
                    country, atmosphere, ending, or a strange moment from the plot.
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
    meta.textContent = role === "user" ? "You" : "AI";

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = text;

    bubble.appendChild(meta);
    bubble.appendChild(content);
    row.appendChild(bubble);
    messagesEl.appendChild(row);

    if (autoScroll) scrollMessagesToBottom();

    return bubble;
}

function showNetflixCard(title, url) {
    extraPanelEl.classList.remove("hidden");
    extraPanelEl.innerHTML = `
        <div class="netflix-card">
            <div>
                <div class="netflix-card-title">Maybe it's: ${escapeHtml(title)}</div>
                <div class="netflix-card-subtitle">
                    Opening Netflix search by title
                </div>
            </div>
            <a class="link-btn" href="${url}" target="_blank" rel="noopener noreferrer">
                Open in Netflix
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
    sendBtnEl.textContent = locked ? "Typing..." : "Send";
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
    return date.toLocaleString("en-US", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}