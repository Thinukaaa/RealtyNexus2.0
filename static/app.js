(function () {
  // --- DOM helpers ---
  const qs  = (sel, el=document) => el.querySelector(sel);
  const qsa = (sel, el=document) => [...el.querySelectorAll(sel)];
  const el  = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  // --- Session ---
  const SESSION_KEY = "realty_session_id";
  const getSid = () => {
    let sid = localStorage.getItem(SESSION_KEY);
    if (!sid) { sid = Math.random().toString(16).slice(2); localStorage.setItem(SESSION_KEY, sid); }
    return sid;
  };

  // --- Widget skeleton ---
  const launcher = el("button", "rn-chat-launcher", "Chat with RealtyAI");
  const chat = el("section", "rn-chat");
  chat.innerHTML = `
    <header class="rn-chat-header">
      <div class="rn-chat-title">RealtyAI</div>
      <button aria-label="Close" class="rn-chat-send" id="rn-close">Close</button>
    </header>
    <div class="rn-chat-body" id="rn-body" aria-live="polite"></div>
    <div class="rn-chat-composer">
      <input id="rn-input" class="rn-chat-input" placeholder="Ask e.g. apartments in Galle under 80M" />
      <button id="rn-send" class="rn-chat-send">Send</button>
    </div>
  `;
  document.body.appendChild(launcher);
  document.body.appendChild(chat);

  const body  = qs("#rn-body", chat);
  const input = qs("#rn-input", chat);
  const send  = qs("#rn-send", chat);
  const close = qs("#rn-close", chat);

  const scrollToBottom = () => {
    // Smooth but not over-eager
    body.scrollTo({ top: body.scrollHeight, behavior: "smooth" });
  };

  const addBubble = (who, text) => {
    if (!text) return;
    const b = el("div", `rn-msg ${who === "me" ? "rn-me" : "rn-bot"}`);
    b.textContent = text;
    body.appendChild(b);
    scrollToBottom();
  };

  const addPreface = (text) => {
    if (!text) return;
    const n = el("div", "rn-note", text);
    body.appendChild(n);
    scrollToBottom();
  };

  const formatPrice = (n) => {
    try { return "LKR " + Number(n).toLocaleString("en-US"); }
    catch { return "LKR " + n; }
  };

  const renderCards = (items, kind="listings") => {
    const wrap = el("div", "rn-grid");
    for (const it of items || []) {
      const c = el("div", "rn-card2");
      const head = el("div", "rn-head");
      if (it.badge) head.appendChild(el("span", "rn-badge", it.badge));
      c.appendChild(head);

      c.appendChild(el("div", "rn-title", it.title || (it.type ? it.type.toUpperCase() : "Listing")));

      if (kind === "listings") {
        const sub = el("div", "rn-sub", it.subtitle || "");
        c.appendChild(sub);
        if (it.price_lkr) c.appendChild(el("div", "rn-price", formatPrice(it.price_lkr)));
        if (it.code) c.appendChild(el("div", "rn-sub", `Code: ${it.code}`));
      } else if (kind === "investments") {
        const sub = el("div", "rn-sub", (it.summary || "").trim());
        c.appendChild(el("div", "rn-sub", it.subtitle || "-"));
        if (sub.textContent) c.appendChild(sub);
        if (it.min_investment_lkr) c.appendChild(el("div", "rn-price", "Min " + formatPrice(it.min_investment_lkr)));
        const metas = [];
        if (it.yield_pct) metas.push(`Yield ~${it.yield_pct}%`);
        if (it.roi_pct) metas.push(`ROI ~${it.roi_pct}%`);
        if (metas.length) c.appendChild(el("div", "rn-sub", metas.join(" · ")));
      }

      wrap.appendChild(c);
    }
    body.appendChild(wrap);
    scrollToBottom();
  };

  // --- Open/close ---
  const openChat = () => { chat.classList.add("open"); input.focus(); };
  const closeChat = () => { chat.classList.remove("open"); };
  launcher.addEventListener("click", openChat);
  close.addEventListener("click", closeChat);

  // --- Boot greeting ---
  addBubble("bot", "Hi! I’m RealtyAI. How can I help you today?");

  // --- Send flow ---
  const sendMessage = async () => {
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    addBubble("me", msg);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: getSid() })
      });
      const data = await res.json();

      // Render reply
      const r = data.reply || {};
      if (r.preface) addPreface(r.preface);
      if (r.type === "cards") {
        addPreface("Here are some options:");
        renderCards(r.items || [], "listings");
      } else if (r.type === "investments") {
        addPreface("Open investment plans:");
        renderCards(r.items || [], "investments");
      } else {
        addBubble("bot", r.content || "…");
      }
    } catch (e) {
      addBubble("bot", "Network error. Please try again.");
      console.error(e);
    }
  };

  send.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
})();
