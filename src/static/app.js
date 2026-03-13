// --- Toast Notifications --- //
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const icons = { success: "✓", error: "✕", info: "i" };

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const icon = document.createElement("span");
    icon.style.fontWeight = "700";
    icon.textContent = icons[type];

    const text = document.createElement("span");
    text.textContent = message;

    toast.appendChild(icon);
    toast.appendChild(text);
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("removing");
        toast.addEventListener("animationend", () => toast.remove());
    }, 3500);
}

// --- State --- //
let phoneCodeHash = "";
let currentSettings = {
    channels: [],
    keywords: [],
    webhook_url: "",
    tg_bot_token: "",
    tg_chat_id: ""
};

// --- Elements --- //
const stepSendCode = document.getElementById("step-send-code");
const stepVerifyCode = document.getElementById("step-verify-code");
const step2fa = document.getElementById("step-2fa");
const authSection = document.getElementById("auth-section");
const settingsSection = document.getElementById("settings-section");
const listChannels = document.getElementById("list-channels");
const inputWebhook = document.getElementById("input-webhook");
const inputTgBotToken = document.getElementById("input-tg-bot-token");
const inputTgChatId = document.getElementById("input-tg-chat-id");

// --- Auth Flow --- //

function setStepDot(num, state) {
    const dot = document.getElementById(`step-dot-${num}`);
    if (!dot) return;
    dot.classList.remove("active", "done");
    if (state) dot.classList.add(state);
}

document.getElementById("btn-request-code").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.innerText = "Requesting...";
    try {
        const res = await fetch("/api/auth/send_code", { method: "POST" });
        const data = await res.json();
        if (data.status === "success") {
            phoneCodeHash = data.phone_code_hash;
            setStepDot(1, "done");
            setStepDot(2, "active");
            stepSendCode.classList.add("hidden");
            stepVerifyCode.classList.remove("hidden");
            stepVerifyCode.classList.add("flex");
        } else {
            showToast(data.message || "Failed to send code.", "error");
        }
    } catch (err) {
        showToast("Network error. Check your connection.", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = "Request Login Code";
    }
});

document.getElementById("btn-submit-code").addEventListener("click", async (e) => {
    const code = document.getElementById("input-code").value.trim();
    if (!code) return;

    const btn = e.target;
    btn.disabled = true;
    btn.innerText = "Verifying...";

    try {
        const res = await fetch("/api/auth/verify_code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code: code, phone_code_hash: phoneCodeHash })
        });
        const data = await res.json();

        if (data.status === "success") {
            handleAuthSuccess();
        } else if (data.status === "2fa_required") {
            setStepDot(2, "done");
            setStepDot(3, "active");
            stepVerifyCode.classList.remove("flex");
            stepVerifyCode.classList.add("hidden");
            step2fa.classList.remove("hidden");
            step2fa.classList.add("flex");
        } else {
            showToast(data.message || "Invalid code.", "error");
        }
    } catch (err) {
        showToast("Network error. Check your connection.", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = "Submit Code";
    }
});

document.getElementById("btn-submit-2fa").addEventListener("click", async (e) => {
    const password = document.getElementById("input-2fa").value;
    if (!password) return;

    const btn = e.target;
    btn.disabled = true;
    btn.innerText = "Unlocking...";

    try {
        const res = await fetch("/api/auth/verify_2fa", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: password })
        });
        const data = await res.json();

        if (data.status === "success") {
            handleAuthSuccess();
        } else {
            showToast(data.message || "Incorrect password.", "error");
        }
    } catch (err) {
        showToast("Network error. Check your connection.", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = "Unlock";
    }
});

function handleAuthSuccess() {
    authSection.classList.add("hidden");
    settingsSection.classList.remove("opacity-40", "pointer-events-none");
    updateStatusIndicator(true);
    showToast("Authorization successful.", "success");
}

// --- Settings Flow --- //

function renderSettings() {
    // Render Channels
    listChannels.innerHTML = "";
    if (!currentSettings.channels.length) {
        const empty = document.createElement("li");
        empty.className = "text-xs text-gray-600 px-1 py-2";
        empty.textContent = "No channels added yet.";
        listChannels.appendChild(empty);
    }
    currentSettings.channels.forEach((c, idx) => {
        const li = document.createElement("li");
        li.className = "flex items-center justify-between text-sm bg-dark-bg px-3 py-2 rounded-lg text-gray-300 border border-dark-border";

        const span = document.createElement("span");
        span.textContent = c;

        const btn = document.createElement("button");
        btn.className = "text-red-400 hover:text-red-300";
        btn.textContent = "✕";
        btn.addEventListener("click", () => removeListItem("channels", idx));

        li.appendChild(span);
        li.appendChild(btn);
        listChannels.appendChild(li);
    });

    renderKeywordsPreview();
    renderModalKeywords();
}

function renderKeywordsPreview() {
    const preview = document.getElementById("keywords-preview");
    if (!preview) return;
    preview.innerHTML = "";

    if (!currentSettings.keywords.length) {
        const empty = document.createElement("span");
        empty.className = "text-xs text-gray-600";
        empty.textContent = "No keywords yet — click Manage to add some.";
        preview.appendChild(empty);
        return;
    }

    const MAX_SHOWN = 6;
    const shown = currentSettings.keywords.slice(0, MAX_SHOWN);
    const rest = currentSettings.keywords.length - MAX_SHOWN;

    shown.forEach(k => {
        const pill = document.createElement("span");
        pill.className = "text-xs bg-primary/15 text-primary px-2.5 py-1 rounded-full font-medium";
        pill.textContent = k;
        preview.appendChild(pill);
    });

    if (rest > 0) {
        const more = document.createElement("span");
        more.className = "text-xs text-gray-500 px-1 py-1";
        more.textContent = `+${rest} more`;
        preview.appendChild(more);
    }
}

function renderModalKeywords() {
    const list = document.getElementById("modal-keywords-list");
    if (!list) return;
    list.innerHTML = "";

    if (!currentSettings.keywords.length) {
        const empty = document.createElement("span");
        empty.className = "text-xs text-gray-600 py-2";
        empty.textContent = "No keywords yet.";
        list.appendChild(empty);
        return;
    }

    currentSettings.keywords.forEach((k, idx) => {
        const pill = document.createElement("span");
        pill.className = "flex items-center gap-1.5 text-sm bg-primary/15 text-primary px-3 py-1.5 rounded-full font-medium";

        const label = document.createElement("span");
        label.textContent = k;

        const btn = document.createElement("button");
        btn.className = "text-primary/60 hover:text-white transition-colors leading-none";
        btn.textContent = "✕";
        btn.addEventListener("click", () => { removeListItem("keywords", idx); });

        pill.appendChild(label);
        pill.appendChild(btn);
        list.appendChild(pill);
    });
}

window.addListItem = function (type) {
    const input = document.getElementById(`input-new-${type.slice(0, -1)}`);
    const val = input.value.trim();
    if (val && !currentSettings[type].includes(val)) {
        currentSettings[type].push(val);
        input.value = "";
        renderSettings();
    }
};

// --- Help Toggles --- //
window.toggleHelp = function(id) {
    document.getElementById(id).classList.toggle("hidden");
};

// --- Keywords Modal --- //

function openKeywordsModal() {
    document.getElementById("keywords-modal").classList.remove("hidden");
    document.body.style.overflow = "hidden";
    setTimeout(() => document.getElementById("input-modal-keyword").focus(), 50);
}

function closeKeywordsModal() {
    document.getElementById("keywords-modal").classList.add("hidden");
    document.body.style.overflow = "";
}

function addModalKeywords() {
    const input = document.getElementById("input-modal-keyword");
    const raw = input.value.trim();
    if (!raw) return;

    const entries = raw.split(",").map(s => s.trim()).filter(s => s.length > 0);
    let added = 0;
    entries.forEach(k => {
        if (!currentSettings.keywords.includes(k)) {
            currentSettings.keywords.push(k);
            added++;
        }
    });
    input.value = "";
    renderSettings();
    if (added > 0) showToast(`Added ${added} keyword${added > 1 ? "s" : ""}.`, "success");
}

document.getElementById("btn-open-keywords").addEventListener("click", openKeywordsModal);
document.getElementById("btn-close-keywords").addEventListener("click", closeKeywordsModal);
document.getElementById("keywords-backdrop").addEventListener("click", closeKeywordsModal);
document.getElementById("btn-add-modal-keyword").addEventListener("click", addModalKeywords);
document.getElementById("input-modal-keyword").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addModalKeywords();
    if (e.key === "Escape") closeKeywordsModal();
});
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("keywords-modal").classList.contains("hidden")) {
        closeKeywordsModal();
    }
});

window.removeListItem = function (type, idx) {
    currentSettings[type].splice(idx, 1);
    renderSettings();
};

document.getElementById("btn-save-settings").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    const originalContent = btn.innerHTML;
    currentSettings.webhook_url = inputWebhook.value.trim();
    currentSettings.tg_bot_token = inputTgBotToken.value.trim();
    currentSettings.tg_chat_id = inputTgChatId.value.trim();

    btn.innerHTML = `<span class="flex items-center gap-2">Saving...</span>`;
    try {
        await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentSettings)
        });
        btn.innerHTML = `<span class="flex items-center gap-2 text-green-400">Saved!</span>`;
        showToast("Settings saved.", "success");
        setTimeout(() => { btn.innerHTML = originalContent; }, 2000);
    } catch (err) {
        showToast("Failed to save settings.", "error");
        btn.innerHTML = originalContent;
    }
});

// Enter key support on channel input
document.getElementById("input-new-channel").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addListItem("channels");
});

// Init
try {
    const dataEl = document.getElementById("initial-data");
    if (dataEl && dataEl.textContent) {
        currentSettings = JSON.parse(dataEl.textContent);
        renderSettings();
    }
} catch (err) {
    console.error("Failed to parse initial settings", err);
}

// --- Status Polling --- //
function updateStatusIndicator(authorized) {
    const container = document.getElementById("auth-status");
    const ping = container.querySelector(".animate-ping");
    const dot = container.querySelectorAll("span span")[1];
    const text = document.getElementById("auth-text");

    if (authorized) {
        container.className = container.className
            .replace("bg-amber-500/10", "bg-green-500/10")
            .replace("text-amber-400", "text-green-400")
            .replace("border-amber-500/20", "border-green-500/20");
        ping.className = ping.className.replace("bg-amber-400", "bg-green-400");
        dot.className = dot.className.replace("bg-amber-500", "bg-green-500");
        text.textContent = "Active Session";
    } else {
        container.className = container.className
            .replace("bg-green-500/10", "bg-amber-500/10")
            .replace("text-green-400", "text-amber-400")
            .replace("border-green-500/20", "border-amber-500/20");
        ping.className = ping.className.replace("bg-green-400", "bg-amber-400");
        dot.className = dot.className.replace("bg-green-500", "bg-amber-500");
        text.textContent = "Require Auth";
    }
}

async function pollStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        updateStatusIndicator(data.authorized);
    } catch (_) {}
}

setInterval(pollStatus, 30000);

// --- Activity Log --- //
function timeAgo(isoString) {
    const diff = Math.floor((Date.now() - new Date(isoString)) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

async function loadEvents() {
    try {
        const res = await fetch("/api/events");
        const events = await res.json();
        const list = document.getElementById("events-list");
        const empty = document.getElementById("events-empty");
        const count = document.getElementById("events-count");

        if (!events.length) {
            empty.classList.remove("hidden");
            count.textContent = "";
            return;
        }

        empty.classList.add("hidden");
        count.textContent = `${events.length} recent`;

        // Only re-render if data changed (compare first event id)
        if (list.dataset.topId === String(events[0].id)) return;
        list.dataset.topId = events[0].id;

        list.innerHTML = "";
        list.appendChild(empty);

        events.forEach(ev => {
            const li = document.createElement("li");
            li.className = "flex flex-col gap-1 bg-dark-bg border border-dark-border rounded-xl px-4 py-3 text-sm";

            const top = document.createElement("div");
            top.className = "flex items-center justify-between gap-2";

            const channelSpan = document.createElement("span");
            channelSpan.className = "text-gray-300 font-medium truncate";
            channelSpan.textContent = ev.channel_name;

            const meta = document.createElement("div");
            meta.className = "flex items-center gap-2 shrink-0";

            const keyword = document.createElement("span");
            keyword.className = "bg-primary/20 text-primary text-xs px-2 py-0.5 rounded-full font-medium";
            keyword.textContent = ev.keyword;

            const time = document.createElement("span");
            time.className = "text-gray-500 text-xs";
            time.textContent = timeAgo(ev.matched_at);

            meta.appendChild(keyword);
            meta.appendChild(time);
            top.appendChild(channelSpan);
            top.appendChild(meta);

            const preview = document.createElement("p");
            preview.className = "text-gray-400 text-xs leading-relaxed line-clamp-2";
            preview.textContent = ev.message_text;

            li.appendChild(top);
            li.appendChild(preview);

            if (ev.message_link && ev.message_link !== "No link available") {
                const link = document.createElement("a");
                link.href = ev.message_link;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.className = "text-primary text-xs hover:underline w-fit";
                link.textContent = "Open in Telegram →";
                li.appendChild(link);
            }

            list.appendChild(li);
        });
    } catch (_) {}
}

loadEvents();
setInterval(loadEvents, 15000);

// --- Webhook Test --- //
document.getElementById("btn-test-webhook").addEventListener("click", async (e) => {
    const btn = e.target;
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "...";
    try {
        const res = await fetch("/api/webhook/test", { method: "POST" });
        const data = await res.json();
        if (data.status === "success") {
            showToast("Test payload sent to webhook.", "success");
        } else {
            showToast(data.message || "Test failed.", "error");
        }
    } catch (_) {
        showToast("Network error.", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
});
