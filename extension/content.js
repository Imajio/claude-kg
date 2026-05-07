// content.js — runs on claude.ai
// Monitors conversations and sends them to local KG server

const SERVER = "http://127.0.0.1:7842";
let lastSentConversation = "";
let debounceTimer = null;

// ── Extract conversation text from the DOM ────────────────────────────────
function extractConversation() {
  const messages = [];

  // Claude.ai uses these selectors for messages
  const humanTurns = document.querySelectorAll(
    '[data-testid="human-turn"], .human-turn, [class*="human"]'
  );
  const assistantTurns = document.querySelectorAll(
    '[data-testid="assistant-turn"], .assistant-turn, [class*="assistant"]'
  );

  // Fallback: grab all message bubbles by structure
  const allTurns = document.querySelectorAll(
    '[data-testid*="turn"], .font-claude-message, [class*="ConversationTurn"]'
  );

  if (allTurns.length > 0) {
    allTurns.forEach((el) => {
      const isHuman =
        el.getAttribute("data-testid")?.includes("human") ||
        el.closest('[data-testid*="human"]') !== null;
      const role = isHuman ? "USER" : "CLAUDE";
      const text = el.innerText?.trim();
      if (text && text.length > 5) {
        messages.push(`### ${role}\n${text}`);
      }
    });
  }

  // Super fallback: just grab all visible text blocks
  if (messages.length === 0) {
    document.querySelectorAll("p, li").forEach((el) => {
      const text = el.innerText?.trim();
      if (text && text.length > 20) {
        messages.push(text);
      }
    });
  }

  return messages.join("\n\n");
}

// ── Get page title as hint ─────────────────────────────────────────────────
function getTitle() {
  return document.title?.replace(" - Claude", "").trim() || "";
}

// ── Send to local server ───────────────────────────────────────────────────
async function sendToServer(conversation, title) {
  try {
    const resp = await fetch(`${SERVER}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation, title }),
    });
    const data = await resp.json();
    return data;
  } catch (e) {
    console.log("[KG] Server not reachable:", e.message);
    return null;
  }
}

// ── Check if server is alive ───────────────────────────────────────────────
async function pingServer() {
  try {
    const resp = await fetch(`${SERVER}/ping`);
    return resp.ok;
  } catch {
    return false;
  }
}

// ── Auto-send when Claude finishes responding ─────────────────────────────
// Watch for the "Stop" button disappearing (= Claude done responding)
const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(async () => {
    // Check if Claude is still generating (stop button visible)
    const isGenerating = document.querySelector(
      '[aria-label="Stop"], [data-testid="stop-button"]'
    );
    if (isGenerating) return; // still generating, wait

    const conversation = extractConversation();
    if (!conversation || conversation === lastSentConversation) return;
    if (conversation.length < 200) return;

    const title = getTitle();
    lastSentConversation = conversation;

    const alive = await pingServer();
    if (!alive) return; // server not running, silently skip

    const result = await sendToServer(conversation, title);
    if (result?.status === "processing") {
      showToast("🧠 Building Obsidian knowledge graph...");
    }
  }, 2000); // wait 2s after last DOM change
});

observer.observe(document.body, {
  childList: true,
  subtree: true,
  characterData: true,
});

// ── Toast notification ─────────────────────────────────────────────────────
function showToast(message) {
  const existing = document.getElementById("kg-toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.id = "kg-toast";
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-family: system-ui;
    z-index: 99999;
    border: 1px solid #333;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    animation: kg-slide-in 0.3s ease;
  `;

  const style = document.createElement("style");
  style.textContent = `
    @keyframes kg-slide-in {
      from { transform: translateY(20px); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Listen for manual trigger from popup ──────────────────────────────────
chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg.action === "extract_now") {
    const conversation = extractConversation();
    const title = getTitle();

    if (!conversation || conversation.length < 100) {
      chrome.runtime.sendMessage({ action: "result", error: "No conversation found" });
      return;
    }

    const alive = await pingServer();
    if (!alive) {
      chrome.runtime.sendMessage({
        action: "result",
        error: "Server not running. Start server.py first.",
      });
      return;
    }

    const result = await sendToServer(conversation, title);
    chrome.runtime.sendMessage({ action: "result", data: result });
    if (result?.status === "processing") {
      showToast("🧠 Building Obsidian knowledge graph...");
    }
  }
});
