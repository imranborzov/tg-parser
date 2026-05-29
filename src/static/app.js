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
let currentInstanceId = null;
let isPaused = false;
let instances = [];
let currentSettings = {
    channels: [],
    keywords: [],
    excluded_keywords: [],
    webhook_url: "",
    tg_bot_token: "",
    tg_chat_id: "",
    match_cooldown: 60,
    api_id: "",
    api_hash: "",
    phone: "",
    include_channels: false
};

// --- Elements --- //
const stepVerifyCode = document.getElementById("step-verify-code");
const step2fa = document.getElementById("step-2fa");
const settingsSection = document.getElementById("settings-section");
const listChannels = document.getElementById("list-channels");
const inputWebhook = document.getElementById("input-webhook");
const inputTgBotToken = document.getElementById("input-tg-bot-token");
const inputTgChatId = document.getElementById("input-tg-chat-id");
const inputMatchCooldown = document.getElementById("input-match-cooldown");
const inputApiId = document.getElementById("input-api-id");
const inputApiHash = document.getElementById("input-api-hash");
const inputPhone = document.getElementById("input-phone");
const accountBadge = document.getElementById("account-badge");
const btnRequestCode = document.getElementById("btn-request-code");
const btnPauseInstance = document.getElementById("btn-pause-instance");
const instanceBar = document.getElementById("instance-bar");
const instanceSelect = document.getElementById("instance-select");
const inputChannelsFile = document.getElementById("input-channels-file");
const btnChooseFile = document.getElementById("btn-choose-file");
const btnUploadChannels = document.getElementById("btn-upload-channels");
const uploadFilename = document.getElementById("upload-filename");
const inputIncludeChannels = document.getElementById("input-include-channels");

// --- Per-instance Auth Flow --- //

function resetAuthSteps() {
    phoneCodeHash = "";
    stepVerifyCode.classList.add("hidden");
    step2fa.classList.add("hidden");
    document.getElementById("input-code").value = "";
    document.getElementById("input-2fa").value = "";
}

// Persist the credentials currently typed in, so auth uses the latest values.
async function saveCurrentCredentials() {
    currentSettings.api_id = inputApiId.value.trim();
    currentSettings.api_hash = inputApiHash.value.trim();
    currentSettings.phone = inputPhone.value.trim();
    await persistSettings();
}

btnRequestCode.addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    if (!inputApiId.value.trim() || !inputApiHash.value.trim() || !inputPhone.value.trim()) {
        showToast("Enter API ID, API hash, and phone first.", "error");
        return;
    }
    const btn = btnRequestCode;
    btn.disabled = true;
    btn.innerText = "Sending...";
    try {
        await saveCurrentCredentials();
        const res = await fetch(`/api/instances/${currentInstanceId}/auth/send_code`, { method: "POST" });
        const data = await res.json();
        if (data.status === "success") {
            phoneCodeHash = data.phone_code_hash;
            stepVerifyCode.classList.remove("hidden");
            document.getElementById("input-code").focus();
            showToast("Login code sent to Telegram.", "success");
        } else {
            showToast(data.message || "Failed to send code.", "error");
        }
    } catch (err) {
        showToast("Network error. Check your connection.", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = "Save & Send Login Code";
    }
});

document.getElementById("btn-submit-code").addEventListener("click", async (e) => {
    const code = document.getElementById("input-code").value.trim();
    if (!code || currentInstanceId === null) return;

    const btn = e.target;
    btn.disabled = true;
    btn.innerText = "Verifying...";

    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/auth/verify_code`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code: code, phone_code_hash: phoneCodeHash })
        });
        const data = await res.json();

        if (data.status === "success") {
            handleAuthSuccess();
        } else if (data.status === "2fa_required") {
            stepVerifyCode.classList.add("hidden");
            step2fa.classList.remove("hidden");
            document.getElementById("input-2fa").focus();
        } else {
            showToast(data.message || "Invalid code.", "error");
        }
    } catch (err) {
        showToast("Network error. Check your connection.", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = "Verify";
    }
});

document.getElementById("btn-submit-2fa").addEventListener("click", async (e) => {
    const password = document.getElementById("input-2fa").value;
    if (!password || currentInstanceId === null) return;

    const btn = e.target;
    btn.disabled = true;
    btn.innerText = "Unlocking...";

    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/auth/verify_2fa`, {
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
    resetAuthSteps();
    refreshAuthStatus();
    showToast("Account connected.", "success");
}

document.getElementById("input-code").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btn-submit-code").click();
});
document.getElementById("input-2fa").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btn-submit-2fa").click();
});

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
    renderExcluded();
}

function renderExcluded() {
    const list = document.getElementById("excluded-list");
    if (!list) return;
    list.innerHTML = "";

    if (!currentSettings.excluded_keywords.length) {
        const empty = document.createElement("span");
        empty.className = "text-xs text-gray-600";
        empty.textContent = "No excluded words — matches won't be filtered.";
        list.appendChild(empty);
        return;
    }

    currentSettings.excluded_keywords.forEach((k, idx) => {
        const pill = document.createElement("span");
        pill.className = "flex items-center gap-1.5 text-sm bg-red-500/10 text-red-300 px-3 py-1.5 rounded-full font-medium";

        const label = document.createElement("span");
        label.textContent = k;

        const btn = document.createElement("button");
        btn.className = "text-red-300/60 hover:text-white transition-colors leading-none";
        btn.textContent = "✕";
        btn.addEventListener("click", () => removeListItem("excluded_keywords", idx));

        pill.appendChild(label);
        pill.appendChild(btn);
        list.appendChild(pill);
    });
}

function addExcluded() {
    const input = document.getElementById("input-new-excluded");
    const raw = input.value.trim();
    if (!raw) return;
    const entries = raw.split(",").map(s => s.trim()).filter(s => s.length > 0);
    let added = 0;
    entries.forEach(k => {
        if (!currentSettings.excluded_keywords.includes(k)) {
            currentSettings.excluded_keywords.push(k);
            added++;
        }
    });
    input.value = "";
    renderSettings();
    if (added > 0) {
        showToast(`Added ${added} excluded word${added > 1 ? "s" : ""}.`, "success");
        autoSave();
    }
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
        autoSave();
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
    if (added > 0) {
        showToast(`Added ${added} keyword${added > 1 ? "s" : ""}.`, "success");
        autoSave();
    }
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
    autoSave();
};

// Debounced silent save triggered by list mutations (add/remove channel, keyword, excluded word).
let _autoSaveTimer = null;
function autoSave() {
    clearTimeout(_autoSaveTimer);
    _autoSaveTimer = setTimeout(async () => {
        if (currentInstanceId === null) return;
        try {
            await persistSettings();
        } catch (_) {
            showToast("Auto-save failed.", "error");
        }
    }, 400);
}

// Gather the editable inputs into currentSettings, then POST to the instance.
async function persistSettings() {
    if (currentInstanceId === null) throw new Error("No instance selected.");
    currentSettings.webhook_url = inputWebhook.value.trim();
    currentSettings.tg_bot_token = inputTgBotToken.value.trim();
    currentSettings.tg_chat_id = inputTgChatId.value.trim();
    currentSettings.match_cooldown = Math.max(0, parseInt(inputMatchCooldown.value) || 0);
    currentSettings.api_id = inputApiId.value.trim();
    currentSettings.api_hash = inputApiHash.value.trim();
    currentSettings.phone = inputPhone.value.trim();
    currentSettings.include_channels = inputIncludeChannels.checked;

    const res = await fetch(`/api/instances/${currentInstanceId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            channels: currentSettings.channels,
            keywords: currentSettings.keywords,
            excluded_keywords: currentSettings.excluded_keywords,
            webhook_url: currentSettings.webhook_url,
            tg_bot_token: currentSettings.tg_bot_token,
            tg_chat_id: currentSettings.tg_chat_id,
            match_cooldown: currentSettings.match_cooldown,
            api_id: currentSettings.api_id,
            api_hash: currentSettings.api_hash,
            phone: currentSettings.phone,
            include_channels: currentSettings.include_channels
        })
    });
    if (!res.ok) throw new Error("Save failed.");
}

document.getElementById("btn-save-settings").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (currentInstanceId === null) {
        showToast("No instance selected.", "error");
        return;
    }
    const originalContent = btn.innerHTML;
    btn.innerHTML = `<span class="flex items-center gap-2">Saving...</span>`;
    try {
        await persistSettings();
        btn.innerHTML = `<span class="flex items-center gap-2 text-green-400">Saved!</span>`;
        showToast("Settings saved.", "success");
        setTimeout(() => { btn.innerHTML = originalContent; }, 2000);
    } catch (err) {
        showToast("Failed to save settings.", "error");
        btn.innerHTML = originalContent;
    }
});

// Auto-save match cooldown when the field loses focus
inputMatchCooldown.addEventListener("blur", () => { autoSave(); });

// Auto-save the "include broadcast channels" toggle on change
inputIncludeChannels.addEventListener("change", () => { autoSave(); });

// Enter key support on channel input
document.getElementById("input-new-channel").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addListItem("channels");
});

// Excluded words input
document.getElementById("btn-add-excluded").addEventListener("click", addExcluded);
document.getElementById("input-new-excluded").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addExcluded();
});

// --- Instances --- //

function applySettingsToInputs() {
    inputWebhook.value = currentSettings.webhook_url || "";
    inputTgBotToken.value = currentSettings.tg_bot_token || "";
    inputTgChatId.value = currentSettings.tg_chat_id || "";
    inputMatchCooldown.value = currentSettings.match_cooldown ?? 60;
    inputApiId.value = currentSettings.api_id || "";
    inputApiHash.value = currentSettings.api_hash || "";
    inputPhone.value = currentSettings.phone || "";
    inputIncludeChannels.checked = !!currentSettings.include_channels;
    resetAuthSteps();
    renderSettings();
}

function renderInstanceSelect() {
    instanceSelect.innerHTML = "";
    instances.forEach(inst => {
        const opt = document.createElement("option");
        opt.value = inst.id;
        opt.textContent = inst.name;
        if (inst.id === currentInstanceId) opt.selected = true;
        instanceSelect.appendChild(opt);
    });
    // Disable delete when only one instance remains
    document.getElementById("btn-delete-instance").disabled = instances.length <= 1;
}

async function loadInstanceSettings(id) {
    const res = await fetch(`/api/instances/${id}`);
    if (!res.ok) return;
    const data = await res.json();
    currentSettings = {
        channels: data.channels || [],
        keywords: data.keywords || [],
        excluded_keywords: data.excluded_keywords || [],
        webhook_url: data.webhook_url || "",
        tg_bot_token: data.tg_bot_token || "",
        tg_chat_id: data.tg_chat_id || "",
        match_cooldown: data.match_cooldown ?? 60,
        api_id: data.api_id || "",
        api_hash: data.api_hash || "",
        phone: data.phone || "",
        include_channels: !!data.include_channels
    };
    applySettingsToInputs();
}

async function selectInstance(id) {
    currentInstanceId = id;
    renderInstanceSelect();
    await loadInstanceSettings(id);
    await refreshAuthStatus();
    // Reset events view then reload for this instance
    const list = document.getElementById("events-list");
    if (list) list.dataset.topId = "";
    await loadEvents();
    _lastJoinedCount = -1;
    await refreshJoinQueue();
}

async function loadInstances(preferredId = null) {
    try {
        const res = await fetch("/api/instances");
        instances = await res.json();
        if (!instances.length) return;
        let target = preferredId;
        if (target === null || !instances.some(i => i.id === target)) {
            target = instances[0].id;
        }
        await selectInstance(target);
    } catch (err) {
        console.error("Failed to load instances", err);
    }
}

instanceSelect.addEventListener("change", (e) => {
    selectInstance(parseInt(e.target.value));
});

document.getElementById("btn-new-instance").addEventListener("click", async () => {
    const name = prompt("Name for the new instance:", "New instance");
    if (name === null) return;
    try {
        const res = await fetch("/api/instances", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim() || "Untitled" })
        });
        const created = await res.json();
        await loadInstances(created.id);
        showToast("Instance created.", "success");
    } catch (_) {
        showToast("Failed to create instance.", "error");
    }
});

document.getElementById("btn-rename-instance").addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    const current = instances.find(i => i.id === currentInstanceId);
    const name = prompt("Rename instance:", current ? current.name : "");
    if (name === null) return;
    try {
        await fetch(`/api/instances/${currentInstanceId}/rename`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim() || "Untitled" })
        });
        await loadInstances(currentInstanceId);
        showToast("Instance renamed.", "success");
    } catch (_) {
        showToast("Failed to rename instance.", "error");
    }
});

document.getElementById("btn-delete-instance").addEventListener("click", async () => {
    if (currentInstanceId === null || instances.length <= 1) return;
    const current = instances.find(i => i.id === currentInstanceId);
    if (!confirm(`Delete instance "${current ? current.name : ""}"? Its settings and activity log will be removed.`)) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}`, { method: "DELETE" });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || "Failed to delete instance.", "error");
            return;
        }
        currentInstanceId = null;
        await loadInstances();
        showToast("Instance deleted.", "success");
    } catch (_) {
        showToast("Failed to delete instance.", "error");
    }
});

// Init
loadInstances();

// --- Per-instance connection status --- //

// Reflect the selected instance's state: authorized (bool) + paused (bool).
// Three states: not connected (amber) / active (green) / paused (blue).
function updateStatus(authorized, paused) {
    isPaused = paused;
    const container = document.getElementById("auth-status");
    const ping = container.querySelector(".animate-ping");
    const dot = container.querySelectorAll("span span")[1];
    const text = document.getElementById("auth-text");

    container.className = "flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full border transition-all";
    ping.className = "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75";
    dot.className = "relative inline-flex rounded-full h-2 w-2";

    if (!authorized) {
        container.className += " text-amber-400 border-amber-500/20 bg-amber-500/10";
        ping.className += " bg-amber-400";
        dot.className += " bg-amber-500";
        text.textContent = "Not connected";
        accountBadge.className = "text-[11px] font-medium px-2.5 py-1 rounded-full border text-amber-400 border-amber-500/20 bg-amber-500/10";
        accountBadge.textContent = "Not connected";
        btnRequestCode.innerText = "Save & Send Login Code";
        btnPauseInstance.disabled = true;
        btnPauseInstance.textContent = "Pause";
        btnPauseInstance.className = btnPauseInstance.className.replace(" !text-amber-400 !border-amber-500/40", "");
    } else if (paused) {
        container.className += " text-blue-400 border-blue-500/20 bg-blue-500/10";
        ping.className += " bg-blue-400";
        dot.className += " bg-blue-500";
        text.textContent = "Paused";
        accountBadge.className = "text-[11px] font-medium px-2.5 py-1 rounded-full border text-green-400 border-green-500/20 bg-green-500/10";
        accountBadge.textContent = "Connected";
        btnRequestCode.innerText = "Reconnect";
        btnPauseInstance.disabled = false;
        btnPauseInstance.textContent = "Resume";
        if (!btnPauseInstance.className.includes("!text-amber-400")) {
            btnPauseInstance.className += " !text-amber-400 !border-amber-500/40";
        }
    } else {
        container.className += " text-green-400 border-green-500/20 bg-green-500/10";
        ping.className += " bg-green-400";
        dot.className += " bg-green-500";
        text.textContent = "Active";
        accountBadge.className = "text-[11px] font-medium px-2.5 py-1 rounded-full border text-green-400 border-green-500/20 bg-green-500/10";
        accountBadge.textContent = "Connected";
        btnRequestCode.innerText = "Reconnect";
        btnPauseInstance.disabled = false;
        btnPauseInstance.textContent = "Pause";
        btnPauseInstance.className = btnPauseInstance.className.replace(" !text-amber-400 !border-amber-500/40", "");
    }
}

async function refreshAuthStatus() {
    if (currentInstanceId === null) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/status`);
        const data = await res.json();
        updateStatus(!!data.authorized, !!data.paused);
    } catch (_) {}
}

setInterval(refreshAuthStatus, 30000);

// --- Pause / Resume --- //
btnPauseInstance.addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    const wasRunning = !isPaused;
    const endpoint = isPaused ? "resume" : "pause";
    btnPauseInstance.disabled = true;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/${endpoint}`, { method: "POST" });
        if (res.ok) {
            await refreshAuthStatus();
            showToast(wasRunning ? "Monitoring paused." : "Monitoring resumed.", "success");
        }
    } catch (_) {
        showToast("Failed to change monitoring state.", "error");
    } finally {
        btnPauseInstance.disabled = false;
    }
});

// --- Bulk channel upload + join queue --- //

let _lastJoinedCount = -1;

btnChooseFile.addEventListener("click", () => inputChannelsFile.click());

inputChannelsFile.addEventListener("change", () => {
    const file = inputChannelsFile.files[0];
    if (file) {
        uploadFilename.textContent = file.name;
        btnUploadChannels.disabled = false;
    } else {
        uploadFilename.textContent = "";
        btnUploadChannels.disabled = true;
    }
});

btnUploadChannels.addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    const file = inputChannelsFile.files[0];
    if (!file) return;

    const original = btnUploadChannels.textContent;
    btnUploadChannels.disabled = true;
    btnUploadChannels.textContent = "Uploading…";
    try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`/api/instances/${currentInstanceId}/channels/upload`, {
            method: "POST",
            body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.detail || "Upload failed.", "error");
            return;
        }
        if (data.found === 0) {
            showToast(data.message || "No links found.", "info");
        } else {
            const skipped = data.skipped ? ` (${data.skipped} already queued)` : "";
            showToast(`Queued ${data.queued} channel${data.queued === 1 ? "" : "s"} to join${skipped}.`, "success");
        }
        inputChannelsFile.value = "";
        uploadFilename.textContent = "";
        await refreshJoinQueue();
    } catch (_) {
        showToast("Network error during upload.", "error");
    } finally {
        btnUploadChannels.textContent = original;
        btnUploadChannels.disabled = !inputChannelsFile.files[0];
    }
});

document.getElementById("btn-clear-queue").addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    try {
        await fetch(`/api/instances/${currentInstanceId}/join_queue/clear`, { method: "POST" });
        await refreshJoinQueue();
    } catch (_) {
        showToast("Failed to clear queue.", "error");
    }
});

let _joinsPaused = false;

document.getElementById("btn-pause-joins").addEventListener("click", async () => {
    if (currentInstanceId === null) return;
    const endpoint = _joinsPaused ? "resume" : "pause";
    const btn = document.getElementById("btn-pause-joins");
    btn.disabled = true;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/join_queue/${endpoint}`, { method: "POST" });
        if (res.ok) {
            showToast(_joinsPaused ? "Joining resumed." : "Joining paused.", "success");
            await refreshJoinQueue();
        }
    } catch (_) {
        showToast("Failed to change joining state.", "error");
    } finally {
        btn.disabled = false;
    }
});

// Pull the channels stored on the server into the list without disturbing the
// text inputs the user may be editing (joins add channels server-side).
async function refreshChannelList() {
    if (currentInstanceId === null) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}`);
        if (!res.ok) return;
        const data = await res.json();
        currentSettings.channels = data.channels || [];
        renderSettings();
    } catch (_) {}
}

function renderJoinQueue(summary, jobs, paused) {
    const box = document.getElementById("join-queue-box");
    const summaryEl = document.getElementById("join-queue-summary");
    const list = document.getElementById("join-queue-list");
    const pauseBtn = document.getElementById("btn-pause-joins");

    _joinsPaused = !!paused;

    const total = (summary.pending || 0) + (summary.joined || 0) + (summary.failed || 0) + (summary.skipped || 0);
    if (total === 0) {
        box.classList.add("hidden");
        list.innerHTML = "";
        return;
    }
    box.classList.remove("hidden");

    // Pause control only matters while there are channels still waiting to join.
    if (summary.pending) {
        pauseBtn.classList.remove("hidden");
        pauseBtn.textContent = _joinsPaused ? "Resume joining" : "Pause joining";
        pauseBtn.className = pauseBtn.className.replace(" text-green-400 hover:text-green-300", "").replace(" text-amber-400 hover:text-amber-300", "");
        pauseBtn.className += _joinsPaused ? " text-green-400 hover:text-green-300" : " text-amber-400 hover:text-amber-300";
    } else {
        pauseBtn.classList.add("hidden");
    }

    const parts = [];
    if (summary.pending) parts.push(_joinsPaused ? `${summary.pending} pending (paused)` : `${summary.pending} pending`);
    if (summary.joined) parts.push(`${summary.joined} joined`);
    if (summary.skipped) parts.push(`${summary.skipped} skipped`);
    if (summary.failed) parts.push(`${summary.failed} failed`);
    summaryEl.textContent = parts.join(" · ");

    list.innerHTML = "";
    jobs.forEach(job => {
        const li = document.createElement("li");
        li.className = "flex items-center justify-between gap-2 text-xs bg-dark-bg px-2.5 py-1.5 rounded-lg border border-dark-border";

        const label = document.createElement("span");
        label.className = "truncate text-gray-400";
        label.textContent = job.kind === "invite" ? `+${job.identifier}` : job.identifier;
        if ((job.status === "failed" || job.status === "skipped") && job.result) label.title = job.result;

        const badge = document.createElement("span");
        badge.className = "shrink-0 px-2 py-0.5 rounded-full font-medium ";
        if (job.status === "joined") {
            badge.className += "bg-green-500/15 text-green-400";
            badge.textContent = "joined";
        } else if (job.status === "failed") {
            badge.className += "bg-red-500/15 text-red-400";
            badge.textContent = "failed";
        } else if (job.status === "skipped") {
            badge.className += "bg-gray-500/15 text-gray-400";
            badge.textContent = "skipped";
        } else {
            badge.className += "bg-amber-500/15 text-amber-400";
            badge.textContent = "pending";
        }

        li.appendChild(label);
        li.appendChild(badge);
        list.appendChild(li);
    });
}

async function refreshJoinQueue() {
    if (currentInstanceId === null) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/join_queue`);
        if (!res.ok) return;
        const data = await res.json();
        renderJoinQueue(data.summary || {}, data.jobs || [], data.paused);
        // When the joined count climbs, new channels were added server-side.
        const joined = data.summary ? data.summary.joined || 0 : 0;
        if (_lastJoinedCount !== -1 && joined > _lastJoinedCount) {
            await refreshChannelList();
        }
        _lastJoinedCount = joined;
    } catch (_) {}
}

setInterval(refreshJoinQueue, 10000);

// --- Activity Log --- //
function timeAgo(isoString) {
    const diff = Math.floor((Date.now() - new Date(isoString)) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

async function loadEvents() {
    if (currentInstanceId === null) return;
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/events`);
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
    if (currentInstanceId === null) {
        showToast("No instance selected.", "error");
        return;
    }
    btn.disabled = true;
    btn.textContent = "...";
    try {
        const res = await fetch(`/api/instances/${currentInstanceId}/webhook/test`, { method: "POST" });
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
