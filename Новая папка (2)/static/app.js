// Telegram Bot Hosting Front-End Client

let activeLogInterval = null;
let currentViewingBotId = null;

// Modal helpers
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
  if (id === "logsModal") {
    clearInterval(activeLogInterval);
    activeLogInterval = null;
    currentViewingBotId = null;
  }
}

// Bot Operations
async function startBot(botId) {
  const btn = document.getElementById(`btn-start-${botId}`);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/bots/${botId}/start`, { method: "POST" });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      location.reload();
    }
  } catch (err) {
    alert(`Ошибка связи с сервером: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function stopBot(botId) {
  const btn = document.getElementById(`btn-stop-${botId}`);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/bots/${botId}/stop`, { method: "POST" });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      location.reload();
    }
  } catch (err) {
    alert(`Ошибка связи с сервером: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function restartBot(botId) {
  const btn = document.getElementById(`btn-restart-${botId}`);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/bots/${botId}/restart`, { method: "POST" });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      location.reload();
    }
  } catch (err) {
    alert(`Ошибка связи с сервером: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deleteBot(botId, name) {
  if (!confirm(`Вы действительно хотите удалить бота "${name}" и все его файлы?`)) {
    return;
  }
  try {
    const res = await fetch(`/api/bots/${botId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      location.reload();
    }
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  }
}

// Logs Modal
async function openLogsModal(botId, name) {
  currentViewingBotId = botId;
  document.getElementById("logsBotTitle").innerText = `Логи бота: ${name}`;
  const term = document.getElementById("logsTerminal");
  term.innerText = "Загрузка логов...";
  openModal("logsModal");

  await fetchLogs();
  if (activeLogInterval) clearInterval(activeLogInterval);
  activeLogInterval = setInterval(fetchLogs, 2500);
}

async function fetchLogs() {
  if (!currentViewingBotId) return;
  try {
    const res = await fetch(`/api/bots/${currentViewingBotId}/logs`);
    const data = await res.json();
    const term = document.getElementById("logsTerminal");
    if (term) {
      term.innerText = data.logs || "Логи пусты.";
      term.scrollTop = term.scrollHeight;
    }
  } catch (err) {
    console.error("Logs fetch error:", err);
  }
}

// Files Modal
let currentFilesBotId = null;
async function openFilesModal(botId, name) {
  currentFilesBotId = botId;
  document.getElementById("filesBotTitle").innerText = `Файлы проекта: ${name}`;
  openModal("filesModal");
  await refreshFilesList();
}

async function refreshFilesList() {
  if (!currentFilesBotId) return;
  const container = document.getElementById("filesList");
  container.innerHTML = "Загрузка списка файлов...";
  try {
    const res = await fetch(`/api/bots/${currentFilesBotId}/files`);
    const data = await res.json();
    if (!data.files || data.files.length === 0) {
      container.innerHTML = "<p style='color:#8b949e'>Файлов пока нет.</p>";
      return;
    }
    let html = "<ul style='list-style:none; padding:0;'>";
    data.files.forEach(f => {
      const sizeKb = (f.size / 1024).toFixed(1);
      html += `<li style='padding:6px 0; border-bottom:1px solid #30363d; display:flex; justify-content:space-between;'>
        <span>📄 <strong>${f.name}</strong></span>
        <span style='color:#8b949e; font-size:0.8rem;'>${sizeKb} KB</span>
      </li>`;
    });
    html += "</ul>";
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `Ошибка загрузки файлов: ${err.message}`;
  }
}

async function uploadBotFiles() {
  if (!currentFilesBotId) return;
  const fileInput = document.getElementById("botFileInput");
  if (!fileInput.files || fileInput.files.length === 0) {
    alert("Выберите файл или ZIP-архив!");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  const btn = document.getElementById("btnUploadFile");
  btn.disabled = true;
  btn.innerText = "Загрузка...";

  try {
    const res = await fetch(`/api/bots/${currentFilesBotId}/upload`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      fileInput.value = "";
      alert("Файлы успешно загружены и распакованы!");
      await refreshFilesList();
    }
  } catch (err) {
    alert(`Ошибка загрузки: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerText = "Загрузить";
  }
}

// Create Bot Form
async function submitCreateBot() {
  const name = document.getElementById("createBotName").value.trim();
  const token = document.getElementById("createBotToken").value.trim();

  if (!name) {
    alert("Введите имя бота!");
    return;
  }
  if (!token) {
    alert("Введите Bot Token из @BotFather!");
    return;
  }

  const btn = document.getElementById("btnSubmitCreate");
  btn.disabled = true;

  try {
    const res = await fetch("/api/bots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, bot_token: token })
    });
    const data = await res.json();
    if (data.error) {
      alert(`Ошибка: ${data.error}`);
    } else {
      location.reload();
    }
  } catch (err) {
    alert(`Ошибка связи: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

// Check subscription real-time button
async function checkSubscriptionNow() {
  const btn = document.getElementById("btnCheckSub");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "Проверка...";
  }
  try {
    const res = await fetch("/api/check-sub");
    const data = await res.json();
    if (data.is_subscribed) {
      alert("✅ Подписка подтверждена!");
      location.href = "/";
    } else {
      alert("⚠️ Подписка не обнаружена. Пожалуйста, подпишитесь на канал!");
    }
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "✅ Проверить подписку";
    }
  }
}

// Admin Controls
async function adminToggleBlock(userId, currentBlocked) {
  const action = currentBlocked ? "разблокировать" : "заблокировать";
  if (!confirm(`Вы действительно хотите ${action} пользователя?`)) return;

  try {
    const res = await fetch(`/api/admin/users/${userId}/block`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_blocked: !currentBlocked })
    });
    const data = await res.json();
    if (data.error) alert(`Ошибка: ${data.error}`);
    else location.reload();
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  }
}

async function adminChangeLimit(userId, currentLimit) {
  const newLimit = prompt("Введите новый лимит ботов:", currentLimit);
  if (newLimit === null || isNaN(newLimit)) return;

  try {
    const res = await fetch(`/api/admin/users/${userId}/limit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: parseInt(newLimit, 10) })
    });
    const data = await res.json();
    if (data.error) alert(`Ошибка: ${data.error}`);
    else location.reload();
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  }
}

async function adminForceStopBot(botId) {
  if (!confirm(`Принудительно остановить бота #${botId}?`)) return;
  try {
    const res = await fetch(`/api/admin/bots/${botId}/stop`, { method: "POST" });
    const data = await res.json();
    if (data.error) alert(`Ошибка: ${data.error}`);
    else location.reload();
  } catch (err) {
    alert(`Ошибка: ${err.message}`);
  }
}
