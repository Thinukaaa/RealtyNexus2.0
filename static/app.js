// static/app.js
(() => {
  const $ = (sel) => document.querySelector(sel);
  const chatToggle = $("#chatToggle") || $("#openChat") || $(".chat-fab");
  const chatPanel  = $("#chatPanel")  || $(".chat-panel");
  const chatBody   = $("#chatBody")   || $(".chat-body");
  const chatInput  = $("#chatInput")  || $("#message") || $(".chat-input");
  const chatSend   = $("#chatSend")   || $("#send")    || $(".chat-send");
  const closeChat  = $("#closeChat")  || $(".chat-close");

  const SESSION_KEY = "rn_session";
  let sessionId = sessionStorage.getItem(SESSION_KEY) || null;

  const el = (t,c,h)=>{const x=document.createElement(t); if(c) x.className=c; if(h!==undefined) x.innerHTML=h; return x;};
  const fmtLKR = n => n==null? "" : ("LKR " + Number(n).toLocaleString("en-LK"));
  const scrollDown = ()=>{ if(chatBody) chatBody.scrollTop = chatBody.scrollHeight; };

  function pushBubble(text, me=false){
    if(!chatBody) return;
    const b = el("div", "bubble " + (me ? "me" : "ai"));
    b.textContent = text;
    chatBody.appendChild(b);
    scrollDown();
  }
  function pushCard({title, subtitle, price_lkr, badge, code}){
    if(!chatBody) return;
    const wrap = el("div","bubble ai");
    const card = el("div","card");
    if(badge) card.appendChild(el("span","tag",badge));
    card.appendChild(el("div","card-title", title || "-"));
    card.appendChild(el("div","card-sub", subtitle || ""));
    const p = el("div","card-price", price_lkr ? fmtLKR(price_lkr) : "");
    if(code) p.title = code;
    card.appendChild(p);
    wrap.appendChild(card);
    chatBody.appendChild(wrap);
    scrollDown();
  }
  function pushInvestmentCard(x){
    pushCard({
      title: x.title + (x.yield_pct ? ` · Yield ~${x.yield_pct}%` : ""),
      subtitle: `${x.badge || "Investment"}${x.subtitle ? " · "+x.subtitle : ""}${x.summary ? " — "+x.summary : ""}`,
      price_lkr: x.min_investment_lkr,
      badge: "Investment",
      code: null
    });
  }

  let typingEl = null;
  const showTyping = ()=>{
    if(!chatBody || typingEl) return;
    typingEl = el("div","bubble ai typing",`<span class="dot"></span><span class="dot"></span><span class="dot"></span>`);
    chatBody.appendChild(typingEl); scrollDown();
  };
  const hideTyping = ()=>{ if(typingEl?.parentNode) typingEl.parentNode.removeChild(typingEl); typingEl=null; };

  async function sendToServer(text){
    showTyping();
    try{
      const res = await fetch("/api/chat", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({message:text, session_id: sessionId})
      });
      const data = await res.json();
      if (data.session_id && sessionId !== data.session_id){
        sessionId = data.session_id; sessionStorage.setItem(SESSION_KEY, sessionId);
      }
      renderReply(data.reply);
    }catch(e){
      console.error(e);
      pushBubble("Network error. Please try again.", false);
    }finally{ hideTyping(); }
  }

  function renderReply(reply){
    if(!reply){ pushBubble("Oops — empty reply.", false); return; }
    if (reply.type === "text"){
      pushBubble(reply.content || "Okay.", false);
    } else if (reply.type === "cards"){
      (reply.items || []).forEach(pushCard);
      if (!reply.items || reply.items.length === 0) pushBubble("No results with those filters.", false);
    } else if (reply.type === "investments"){
      (reply.items || []).forEach(pushInvestmentCard);
      if (!reply.items || reply.items.length === 0) pushBubble("No open investment plans right now.", false);
    } else {
      pushBubble(typeof reply === "string" ? reply : JSON.stringify(reply), false);
    }
  }

  chatSend?.addEventListener("click", ()=>{
    const text = (chatInput?.value || "").trim();
    if(!text) return;
    pushBubble(text, true);
    if (chatInput) chatInput.value = "";
    sendToServer(text);
  });
  chatInput?.addEventListener("keydown",(e)=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); chatSend?.click(); }});
  chatToggle?.addEventListener("click",()=> chatPanel?.classList.toggle("open"));
  closeChat?.addEventListener("click",()=> chatPanel?.classList.remove("open"));

  // greet if empty
  if (chatBody && chatBody.children.length === 0){
    pushBubble('Hi! I’m RealtyAI. Tell me city, property type, and budget. Example: “3BR apartments in Galle under 80M”.', false);
  }
})();
