(() => {
  const $ = (sel, el=document) => el.querySelector(sel);
  const chat = $("#rn-chat");
  const toggleBtn = $("#rn-chat-toggle");
  const closeBtn = $("#rn-chat-close");
  const form = $("#rn-chat__form");
  const input = $("#rn-chat__input");
  const log = $("#rn-chat__messages");
  const chipsWrap = $("#rn-quick-replies");

  const api = "/api/chat";
  const sessionKey = "rn_session_id";
  let sessionId = localStorage.getItem(sessionKey) || "";

  function ensureSession() {
    if (!sessionId) {
      sessionId = cryptoRandom();
      localStorage.setItem(sessionKey, sessionId);
    }
  }
  function cryptoRandom(){
    try {
      const arr = new Uint8Array(8); crypto.getRandomValues(arr);
      return [...arr].map(b=>b.toString(16).padStart(2,"0")).join("");
    } catch(e){ return Math.random().toString(16).slice(2,18); }
  }

  function openChat(){
    chat.setAttribute("aria-hidden","false");
    toggleBtn.setAttribute("aria-expanded","true");
    setTimeout(() => input.focus(), 50);
  }
  function closeChat(){
    chat.setAttribute("aria-hidden","true");
    toggleBtn.setAttribute("aria-expanded","false");
  }
  toggleBtn.addEventListener("click",()=>{
    const open = chat.getAttribute("aria-hidden") === "false";
    if(open) closeChat(); else openChat();
  });
  closeBtn.addEventListener("click", closeChat);

  function scrollToBottom(){
    log.scrollTop = log.scrollHeight + 999;
  }
  function bubble(role, text){
    const div = document.createElement("div");
    div.className = `bubble ${role==='user'?'bubble--user':'bubble--bot'}`;
    div.textContent = text;
    log.appendChild(div);
    scrollToBottom();
  }
  function money(n){
    if(n == null) return "";
    try { return "LKR " + Number(n).toLocaleString(); } catch(e){ return "LKR " + n; }
  }

  function renderCards(reply){
    if (reply.preface) {
      bubble("bot", reply.preface + "\nHere are some options:");
    }
    const wrap = document.createElement("div");
    wrap.className = "bubble bubble--bot";
    const grid = document.createElement("div");
    grid.className = "cards";

    (reply.items || []).forEach(it => {
      const card = document.createElement("div");
      card.className = "card";
      if (it.badge){
        const b = document.createElement("span");
        b.className = "badge"; b.textContent = it.badge; card.appendChild(b);
      }
      const t = document.createElement("div");
      t.className = "title"; t.textContent = it.title; card.appendChild(t);

      const s = document.createElement("div");
      s.className = "subtitle"; s.textContent = it.subtitle || ""; card.appendChild(s);

      const meta = document.createElement("div");
      meta.className = "price";
      meta.textContent = money(it.price_lkr);
      card.appendChild(meta);

      if (it.code){
        const c = document.createElement("div");
        c.className = "subtitle"; c.textContent = `Code: ${it.code}`;
        card.appendChild(c);
      }
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    log.appendChild(wrap);
    scrollToBottom();
  }

  function renderInvestments(reply){
    const wrap = document.createElement("div");
    wrap.className = "bubble bubble--bot";
    (reply.items || []).forEach(it => {
      const box = document.createElement("div");
      box.className = "investment";
      if (it.badge){
        const b = document.createElement("span");
        b.className = "badge"; b.textContent = it.badge; box.appendChild(b);
      }
      const t = document.createElement("div");
      t.className = "title"; t.textContent = it.title || "Investment Plan"; box.appendChild(t);

      const meta = document.createElement("div");
      meta.className = "subtitle";
      const bits = [];
      if (it.subtitle) bits.push(it.subtitle);
      if (it.yield_pct) bits.push(`Yield ~${it.yield_pct}%`);
      if (it.roi_pct) bits.push(`ROI ~${it.roi_pct}%`);
      meta.textContent = bits.join(" · ");
      box.appendChild(meta);

      const min = document.createElement("div");
      min.className = "price";
      if (it.min_investment_lkr) min.textContent = "Min investment " + money(it.min_investment_lkr);
      box.appendChild(min);

      if (it.summary){
        const s = document.createElement("div");
        s.className = "subtitle"; s.textContent = it.summary;
        box.appendChild(s);
      }
      wrap.appendChild(box);
    });
    log.appendChild(wrap);
    scrollToBottom();
  }

  function setQuickReplies(kind="default"){
    chipsWrap.innerHTML = "";
    let chips = [];
    if (kind === "hello"){
      chips = [
        "3BR apartments in Galle under 80M",
        "Houses in Kandy under 100M",
        "Show investment plans",
        "Reset"
      ];
    } else if (kind === "refine"){
      chips = [
        "Apartments in Colombo 5 under 50M",
        "Houses in Galle under 80M",
        "Land in Kandy under 30M",
        "Contact an agent"
      ];
    } else {
      chips = [
        "What services do you offer?",
        "What cities do you cover?",
        "Show me apartments",
        "Reset"
      ];
    }
    chips.forEach(txt => {
      const c = document.createElement("button");
      c.type = "button"; c.className = "qr-chip"; c.textContent = txt;
      c.addEventListener("click", ()=>{ input.value = txt; form.dispatchEvent(new Event("submit",{cancelable:true})); });
      chipsWrap.appendChild(c);
    });
  }

  async function sendMessage(msg){
    ensureSession();
    bubble("user", msg);
    input.value = ""; input.focus();
    setQuickReplies("refine");

    const typing = document.createElement("div");
    typing.className = "bubble bubble--bot";
    typing.textContent = "…";
    log.appendChild(typing);
    scrollToBottom();

    try{
      const res = await fetch(api, {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ message: msg, session_id: sessionId })
      });
      const data = await res.json();
      typing.remove();

      const reply = data.reply || {type:"text", content:"Sorry—I had trouble generating a reply just now."};
      if (reply.type === "text"){
        bubble("bot", reply.content || "");
        const txt = (reply.content||"").toLowerCase();
        if (txt.includes("tell me city")) setQuickReplies("hello");
        else setQuickReplies("refine");
      } else if (reply.type === "cards"){
        renderCards(reply);
        setQuickReplies("refine");
      } else if (reply.type === "investments"){
        renderInvestments(reply);
        setQuickReplies("refine");
      } else {
        bubble("bot", "Okay.");
      }
    }catch(err){
      typing.remove();
      bubble("bot", "Sorry—I had trouble generating a reply just now.");
    }
  }

  form.addEventListener("submit", (e)=>{
    e.preventDefault();
    const msg = input.value.trim();
    if(!msg) return;
    sendMessage(msg);
  });

  // Open chat on first load and greet
  if(sessionStorage.getItem("rn_greeted")!=="1"){
    setTimeout(()=>{
      chat.setAttribute("aria-hidden","false");
      toggleBtn.setAttribute("aria-expanded","true");
      bubble("bot", "Hi! I’m RealtyAI. How can I help you today?");
      setQuickReplies("hello");
      sessionStorage.setItem("rn_greeted","1");
    }, 300);
  }

  window.addEventListener("resize", ()=>{
    log.scrollTop = log.scrollHeight + 999;
  });
})();
