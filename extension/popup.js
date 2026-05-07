// popup.js
const SERVER = "http://127.0.0.1:7842";

const statusEl   = document.getElementById("status");
const statusText = document.getElementById("status-text");
const btnExtract = document.getElementById("btn-extract");
const btnAuto    = document.getElementById("btn-auto");
const autoLabel  = document.getElementById("auto-label");
const msgEl      = document.getElementById("msg");

function setMsg(text, type = "") {
  msgEl.textContent = text;
  msgEl.className = "msg " + type;
}

// ── Check server status ───────────────────────────────────────────────────
async function checkServer() {
  try {
    const resp = await fetch(`${SERVER}/ping`, { signal: AbortSignal.timeout(2000) });
    if (resp.ok) {
      statusEl.className = "status ok";
      statusText.textContent = "Server running ✓";
      btnExtract.disabled = false;
      return true;
    }
  } catch {}
  statusEl.className = "status error";
  statusText.textContent = "Server not running";
  btnExtract.disabled = true;
  return false;
}

// ── Manual extract button ─────────────────────────────────────────────────
btnExtract.addEventListener("click", async () => {
  btnExtract.disabled = true;
  btnExtract.textContent = "Processing...";
  setMsg("");

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  chrome.tabs.sendMessage(tab.id, { action: "extract_now" });

  // Listen for result
  chrome.runtime.onMessage.addListener(function listener(msg) {
    if (msg.action === "result") {
      chrome.runtime.onMessage.removeListener(listener);
      btnExtract.disabled = false;
      btnExtract.textContent = "⚡ Save conversation now";

      if (msg.error) {
        setMsg(msg.error, "error");
      } else {
        setMsg("✓ Sent to Obsidian!", "success");
        setTimeout(() => setMsg(""), 3000);
      }
    }
  });

  // Timeout fallback
  setTimeout(() => {
    btnExtract.disabled = false;
    btnExtract.textContent = "⚡ Save conversation now";
  }, 10000);
});

// ── Auto-save toggle ──────────────────────────────────────────────────────
chrome.storage.local.get("autoSave", ({ autoSave }) => {
  const enabled = autoSave !== false; // default ON
  autoLabel.textContent = enabled ? "ON" : "OFF";
  chrome.storage.local.set({ autoSave: enabled });
});

btnAuto.addEventListener("click", () => {
  chrome.storage.local.get("autoSave", ({ autoSave }) => {
    const newVal = !autoSave;
    chrome.storage.local.set({ autoSave: newVal });
    autoLabel.textContent = newVal ? "ON" : "OFF";
    setMsg(newVal ? "Auto-save enabled" : "Auto-save disabled");
    setTimeout(() => setMsg(""), 2000);
  });
});

// ── Init ──────────────────────────────────────────────────────────────────
checkServer();
setInterval(checkServer, 5000);
