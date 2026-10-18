(function () {
  if (location.pathname === "/llbot-ai-config.html") return;
  const BRIDGE = "http://127.0.0.1:8001";
  const NAV_ID = "llbot-ai-config-nav";
  const PANEL_ID = "llbot-ai-config-panel";

  const fields = [
    ["base", "基础连接", "section"],
    ["enabled", "总开关", "checkbox"],
    ["onebot.ws_url", "OneBot WebSocket 地址", "text"],
    ["onebot.access_token", "OneBot Token", "password"],
    ["chat_section", "聊天回复", "section"],
    ["chat.enabled", "聊天开关", "checkbox"],
    ["chat.base_url", "聊天 API Base URL", "text"],
    ["chat.api_key", "聊天 API Key", "password"],
    ["chat.model", "聊天模型", "text"],
    ["chat.trigger", "聊天触发词", "text"],
    ["chat.reply_to_all", "无触发词也自动回复", "checkbox"],
    ["chat.system_prompt", "聊天提示词", "textarea"],
    ["proactive_section", "群聊主动聊天", "section"],
    ["proactive.enabled", "群聊主动聊天", "checkbox"],
    ["proactive.probability", "主动聊天概率 0-1", "number"],
    ["proactive.cooldown_seconds", "主动聊天冷却秒数", "number"],
    ["proactive.min_recent_messages", "触发前最少群消息数", "number"],
    ["proactive.active_window_seconds", "群聊活跃窗口秒数", "number"],
    ["proactive.min_seconds_after_bot_reply", "机器人发言后沉默秒数", "number"],
    ["proactive.prompt", "主动聊天提示词", "textarea"],
    ["contextual_section", "群聊语义接话", "section"],
    ["contextual_reply.enabled", "语义接话开关", "checkbox"],
    ["contextual_reply.cooldown_seconds", "语义接话冷却秒数", "number"],
    ["contextual_reply.ambiguous_probability", "模糊接话概率 0-1", "number"],
    ["contextual_reply.followup_window_seconds", "追问延续窗口秒数", "number"],
    ["contextual_reply.active_window_seconds", "群聊上下文窗口秒数", "number"],
    ["contextual_reply.min_recent_messages", "判断前最少群消息数", "number"],
    ["memory_section", "三层记忆", "section"],
    ["memory.enabled", "记忆总开关", "checkbox"],
    ["memory.summary_enabled", "中期自动摘要", "checkbox"],
    ["memory.long_term_enabled", "长期事实/人物画像", "checkbox"],
    ["memory.summary_every_messages", "每多少条更新摘要", "number"],
    ["memory.summary_recent_limit", "摘要读取最近消息数", "number"],
    ["memory.long_term_max_items", "长期记忆最大条数", "number"],
    ["memory.retrieval_limit", "每次检索记忆条数", "number"],
    ["voice_section", "群 AI 语音", "section"],
    ["voice.enabled", "群 AI 语音开关", "checkbox"],
    ["voice.trigger", "群 AI 语音触发词", "text"],
    ["voice.character", "群 AI 语音音色ID/名称", "text"],
    ["voice.chat_type", "群 AI 语音 Chat Type", "number"],
    ["image_section", "图片生成", "section"],
    ["image.enabled", "生图开关", "checkbox"],
    ["image.base_url", "生图 API Base URL", "text"],
    ["image.api_key", "生图 API Key", "password"],
    ["image.model", "生图模型", "text"],
    ["image.trigger", "生图触发词", "text"],
    ["image.size", "图片尺寸（auto 或 1254x1254 等）", "text"],
    ["image_edit_section", "图生图", "section"],
    ["image_edit.enabled", "图生图开关", "checkbox"],
    ["image_edit.base_url", "图生图 API Base URL", "text"],
    ["image_edit.api_key", "图生图 API Key", "password"],
    ["image_edit.model", "图生图模型", "text"],
    ["image_edit.size", "图片尺寸", "text"],
    ["image_edit.timeout_seconds", "请求超时（秒）", "number"],
    ["image_edit.safety_rewrite", "安全提示词改写", "checkbox"],
  ];

  function get(obj, path) {
    return path.split(".").reduce((acc, key) => (acc ? acc[key] : undefined), obj);
  }

  function set(obj, path, value) {
    const parts = path.split(".");
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      cur[parts[i]] = cur[parts[i]] || {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  function inputHtml(path, label, type, config) {
    if (type === "section") {
      return `<div class="ai-section">${label}</div>`;
    }
    const value = get(config, path);
    const hasSecret = path.endsWith("api_key") || path.endsWith("access_token");
    const placeholder = hasSecret && value === "" ? "已设置则留空不变" : "";
    if (type === "checkbox") {
      return `<label class="ai-row ai-check"><span>${label}</span><input data-field="${path}" type="checkbox" ${value ? "checked" : ""}></label>`;
    }
    if (type === "textarea") {
      return `<label class="ai-row ai-stack"><span>${label}</span><textarea data-field="${path}" rows="4">${escapeHtml(value || "")}</textarea></label>`;
    }
    return `<label class="ai-row ai-stack"><span>${label}</span><input data-field="${path}" type="${type}" value="${escapeHtml(value || "")}" placeholder="${placeholder}"></label>`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[ch]));
  }

  async function loadConfig() {
    const response = await fetch(`${BRIDGE}/api/config`);
    if (!response.ok) throw new Error(`AI Bridge 未启动或不可访问：${response.status}`);
    const body = await response.json();
    return body.data;
  }

  async function saveConfig(panel) {
    const payload = {};
    panel.querySelectorAll("[data-field]").forEach((el) => {
      const path = el.getAttribute("data-field");
      const value = el.type === "checkbox" ? el.checked : el.value;
      set(payload, path, value);
    });
    const response = await fetch(`${BRIDGE}/api/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`保存失败：${response.status}`);
    return response.json();
  }

  function installStyle() {
    if (document.getElementById("llbot-ai-config-style")) return;
    const style = document.createElement("style");
    style.id = "llbot-ai-config-style";
    style.textContent = `
      #${PANEL_ID} { position:fixed; inset:0; z-index:10001; display:flex; align-items:center; justify-content:center; padding:24px; background:rgba(0,0,0,.48); backdrop-filter:blur(4px); color: var(--text-color, #f5f5f5); }
      #${PANEL_ID} .ai-card { background: rgba(255,255,255,.94); color: #171717; border-radius: 8px; padding: 24px; box-shadow: 0 20px 60px rgba(0,0,0,.18); }
      #${PANEL_ID} .ai-card { width:min(1080px, 100%); max-height:calc(100vh - 48px); overflow:auto; }
      .dark #${PANEL_ID} .ai-card { background: rgba(23,23,23,.94); color: #f5f5f5; }
      #${PANEL_ID} .ai-title { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:20px; }
      #${PANEL_ID} h2 { margin:0; font-size:24px; font-weight:700; }
      #${PANEL_ID} .ai-sub { margin:4px 0 0; opacity:.68; font-size:14px; }
      #${PANEL_ID} .ai-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
      #${PANEL_ID} .ai-section { grid-column:1/-1; margin-top:6px; padding:10px 0 2px; border-bottom:1px solid rgba(128,128,128,.22); font-size:15px; font-weight:800; }
      #${PANEL_ID} .ai-row { background: rgba(128,128,128,.10); border: 1px solid rgba(128,128,128,.18); border-radius: 8px; padding:12px; }
      #${PANEL_ID} .ai-stack { display:flex; flex-direction:column; gap:8px; }
      #${PANEL_ID} .ai-check { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:50px; }
      #${PANEL_ID} span { font-size:13px; font-weight:600; opacity:.78; }
      #${PANEL_ID} input[type="text"], #${PANEL_ID} input[type="password"], #${PANEL_ID} input[type="number"], #${PANEL_ID} textarea { width:100%; box-sizing:border-box; border-radius:8px; border:1px solid rgba(128,128,128,.28); background:rgba(255,255,255,.72); color:#171717; padding:10px 12px; outline:none; }
      .dark #${PANEL_ID} input[type="text"], .dark #${PANEL_ID} input[type="password"], .dark #${PANEL_ID} input[type="number"], .dark #${PANEL_ID} textarea { background:rgba(0,0,0,.22); color:#f5f5f5; }
      #${PANEL_ID} .ai-actions { display:flex; justify-content:flex-end; align-items:center; gap:12px; margin-top:18px; }
      #${PANEL_ID} .ai-btn { border:0; border-radius:8px; padding:10px 16px; font-weight:700; cursor:pointer; }
      #${PANEL_ID} .ai-secondary { color:inherit; background:rgba(128,128,128,.16); }
      #${PANEL_ID} .ai-primary { color:white; background:linear-gradient(135deg,#ec4899,#f43f5e); }
      #${PANEL_ID} .ai-status { font-size:13px; opacity:.75; }
      #${NAV_ID} { width:100%; display:flex; align-items:center; gap:.75rem; padding:.75rem 1rem; border:0; border-radius:1rem; background:transparent; font:inherit; text-align:left; cursor:pointer; transition:all .2s; }
      #${NAV_ID}:hover { background:rgba(128,128,128,.14); }
      #${NAV_ID}:focus-visible { outline:2px solid #ec4899; outline-offset:2px; }
      @media (max-width: 800px) { #${PANEL_ID} .ai-grid { grid-template-columns:1fr; } }
    `;
    document.head.appendChild(style);
  }

  async function renderPanel() {
    if (location.hash !== "#ai-config" && !window.__llbotAiConfigOpen) return;
    window.__llbotAiConfigLastStep = "render:start";
    installStyle();
    document.getElementById(PANEL_ID)?.remove();
    document.body.insertAdjacentHTML("beforeend", `<div id="${PANEL_ID}"><div class="ai-card"><div class="ai-title"><div><h2>AI配置</h2><p class="ai-sub">连接 LLBot OneBot 11，实现聊天、/画图 生图和群 AI 语音。</p></div><button class="ai-btn ai-secondary" data-close>关闭</button></div><div class="ai-status">正在读取配置...</div></div></div>`);
    window.__llbotAiConfigLastStep = "render:inserted";
    const panel = document.getElementById(PANEL_ID);
    panel.querySelector("[data-close]")?.addEventListener("click", closePanel);
    panel.addEventListener("click", (event) => {
      if (event.target === panel) closePanel();
    });
    try {
      const config = await loadConfig();
      window.__llbotAiConfigLastStep = "render:loaded";
      panel.querySelector(".ai-card").innerHTML = `<div class="ai-title"><div><h2>AI配置</h2><p class="ai-sub">聊天触发：${escapeHtml(config.chat.trigger)}；生图触发：${escapeHtml(config.image.trigger)}；语音触发：${escapeHtml(config.voice?.trigger || "/语音")}</p></div><button class="ai-btn ai-secondary" data-close>关闭</button></div><div class="ai-grid">${fields.map(([path, label, type]) => inputHtml(path, label, type, config)).join("")}</div><div class="ai-actions"><span class="ai-status">API Key 留空保存时会保留原值。</span><a class="ai-btn ai-secondary" href="http://127.0.0.1:8001/voice-characters" target="_blank">声色列表页</a><button class="ai-btn ai-primary" data-save>保存配置</button></div>`;
      panel.querySelector("[data-close]")?.addEventListener("click", closePanel);
      panel.querySelectorAll("[data-save]").forEach((button) => {
        button.addEventListener("click", async () => {
          const status = panel.querySelector(".ai-status");
          status.textContent = "保存中...";
          try {
            await saveConfig(panel);
            status.textContent = "已保存，AI Bridge 会自动使用新配置。";
          } catch (err) {
            status.textContent = err.message || String(err);
          }
        });
      });
    } catch (err) {
      window.__llbotAiConfigLastStep = "render:error:" + (err.message || String(err));
      panel.querySelector(".ai-status").textContent = err.message || String(err);
    }
  }

  function closePanel() {
    window.__llbotAiConfigOpen = false;
    document.getElementById(PANEL_ID)?.remove();
    if (location.hash === "#ai-config") history.replaceState(null, "", "#dashboard");
  }

  function installNav() {
    const nav = document.querySelector("nav");
    if (!nav || document.getElementById(NAV_ID)) return;
    const button = document.createElement("button");
    button.id = NAV_ID;
    button.type = "button";
    button.className = "w-full flex items-center px-4 py-3 rounded-2xl transition-all duration-200 text-theme hover:bg-theme-item-hover";
    button.title = "AI配置";
    button.setAttribute("aria-label", "AI配置");
    const source = [...nav.querySelectorAll("button")].find(item => item.textContent.trim() === "其他配置");
    const icon = source?.querySelector("svg")?.cloneNode(true);
    if (icon) button.appendChild(icon);
    const label = document.createElement("span");
    label.className = "font-medium";
    label.textContent = "AI配置";
    button.appendChild(label);
    nav.appendChild(button);
  }

  function openPanel(event) {
    window.__llbotAiConfigLastStep = "openPanel";
    event?.preventDefault();
    event?.stopPropagation();
    location.href = "/llbot-ai-config.html";
  }

  window.openLLBotAIConfig = function () {
    openPanel();
  };

  function tick() {
    installStyle();
    installNav();
    if (location.hash === "#ai-config") openPanel();
  }

  document.addEventListener("click", (event) => {
    if (event.target?.closest?.(`#${NAV_ID}`)) openPanel(event);
  }, true);

  window.addEventListener("hashchange", () => {
    window.__llbotAiConfigOpen = location.hash === "#ai-config";
    setTimeout(tick, 50);
  });
  new MutationObserver(tick).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(tick, 1000);
  tick();
})();
