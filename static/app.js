/* RealtyAI Chat – bubbles, typing animation, timestamps, auto-scroll */

(() => {
  const $ = sel => document.querySelector(sel);
  const byId = id => document.getElementById(id);

  const elChat = byId('rn-chat');
  const elMessages = byId('rn-messages');
  const elInput = byId('rn-input');
  const elSend = byId('rn-send');
  const elLauncher = byId('rn-launcher');
  const elClose = byId('rn-close');
  const elChips = byId('rn-suggestions');

  if (!elChat || !elMessages || !elInput || !elSend || !elLauncher || !elClose || !elChips) {
    console.warn('[RealtyAI] Chat elements missing. Skipping boot.');
    return;
  }

  /* ---------- Session ---------- */
  let sessionId = localStorage.getItem('rn_session_id');
  if (!sessionId) {
    sessionId = Math.random().toString(16).slice(2);
    localStorage.setItem('rn_session_id', sessionId);
  }

  /* ---------- Helpers ---------- */
  const fmtTime = (d = new Date()) =>
    d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  const scrollToBottom = (smooth = true) => {
    elMessages.scrollTo({ top: elMessages.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  const makeBubble = (role, html, when = new Date()) => {
    const row = document.createElement('div');
    row.className = `rn-msg ${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'rn-bubble';
    bubble.innerHTML = html;
    const meta = document.createElement('div');
    meta.className = 'rn-meta';
    meta.textContent = fmtTime(when);
    row.appendChild(bubble);
    row.appendChild(meta);
    elMessages.appendChild(row);
    scrollToBottom();
    return row;
  };

  /* ---------- Typing Indicator ---------- */
  let typingEl = null;
  const showTyping = () => {
    if (typingEl) return;
    const row = document.createElement('div');
    row.className = 'rn-msg bot';
    const bubble = document.createElement('div');
    bubble.className = 'rn-bubble';
    bubble.innerHTML = `
      <span class="rn-typing">
        <span class="dot"></span><span class="dot"></span><span class="dot"></span>
      </span>
    `;
    row.appendChild(bubble);
    elMessages.appendChild(row);
    typingEl = row;
    scrollToBottom();
  };
  const hideTyping = () => {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  };

  /* ---------- Cards Renderer ---------- */
  const numberFmt = n => (typeof n === 'number' ? n.toLocaleString('en-LK') : n);

  const renderCards = (items = []) => {
    const grid = document.createElement('div');
    grid.className = 'rn-card-list';
    items.forEach(it => {
      const card = document.createElement('div');
      card.className = 'rn-card';
      const sub = it.subtitle || '';
      const price = (it.price_lkr != null) ? `LKR ${numberFmt(it.price_lkr)}` : (it.min_investment_lkr != null ? `Min LKR ${numberFmt(it.min_investment_lkr)}` : '');
      card.innerHTML = `
        <div class="rn-ttl">${it.title || 'Listing'}</div>
        ${sub ? `<div class="rn-sub">${sub}</div>` : ''}
        ${price ? `<div class="rn-price">${price}</div>` : ''}
      `;
      grid.appendChild(card);
    });
    return grid;
  };

  /* ---------- Suggestions (context-aware) ---------- */
  const setChips = (labels = []) => {
    elChips.innerHTML = '';
    labels.forEach(text => {
      const b = document.createElement('button');
      b.className = 'rn-chip';
      b.textContent = text;
      b.addEventListener('click', () => {
        elInput.value = text;
        elInput.focus();
        sendMessage();
      });
      elChips.appendChild(b);
    });
  };

  const suggestFor = (reply) => {
    // Simple heuristics based on reply.type or text content
    if (!reply) return setChips(['3BR apartments in Galle under 80M','Houses in Kandy under 100M','Show investment plans','Reset']);

    if (reply.type === 'cards') {
      setChips(['Increase budget by 25%','Filter by 3+ bedrooms','Show investment plans','Reset']);
      return;
    }
    if (reply.type === 'investments') {
      setChips(['Minimum investment?','Details on Income Fund A','Contact an advisor','Show residential listings','Reset']);
      return;
    }
    const text = (reply.content || '').toLowerCase();
    if (text.includes('tell me city') || text.includes('property type')) {
      setChips(['Apartments in Colombo 5 under 50M','Houses in Galle under 80M','Land in Kandy under 30M','Show investment plans']);
      return;
    }
    setChips(['3BR apartments in Galle under 80M','Houses in Kandy under 100M','Show investment plans','Reset']);
  };

  /* ---------- Message Flow ---------- */
  const renderReply = (reply) => {
    // reply = { type: 'text'|'cards'|'investments', content?, items?, preface? }
    if (!reply) return;

    if (reply.preface) {
      makeBubble('bot', escapeHtml(reply.preface));
    }

    if (reply.type === 'text') {
      makeBubble('bot', escapeHtml(reply.content || ''));
    } else if (reply.type === 'cards') {
      if (!reply.preface) {
        makeBubble('bot', 'Here are some options:');
      }
      const wrapper = document.createElement('div');
      wrapper.className = 'rn-msg bot';
      const bubble = document.createElement('div');
      bubble.className = 'rn-bubble';
      bubble.appendChild(renderCards(reply.items || []));
      wrapper.appendChild(bubble);
      const meta = document.createElement('div');
      meta.className = 'rn-meta';
      meta.textContent = fmtTime(new Date());
      wrapper.appendChild(meta);
      elMessages.appendChild(wrapper);
      scrollToBottom();
    } else if (reply.type === 'investments') {
      makeBubble('bot', 'Open allocations & plans:');
      const wrapper = document.createElement('div');
      wrapper.className = 'rn-msg bot';
      const bubble = document.createElement('div');
      bubble.className = 'rn-bubble';
      bubble.appendChild(renderCards(reply.items || []));
      wrapper.appendChild(bubble);
      const meta = document.createElement('div');
      meta.className = 'rn-meta';
      meta.textContent = fmtTime(new Date());
      wrapper.appendChild(meta);
      elMessages.appendChild(wrapper);
      scrollToBottom();
    } else {
      makeBubble('bot', escapeHtml(reply.content || ''));
    }

    suggestFor(reply);
  };

  const escapeHtml = (s) =>
    (s || '').replace(/&/g, '&amp;')
             .replace(/</g, '&lt;')
             .replace(/>/g, '&gt;')
             .replace(/"/g, '&quot;')
             .replace(/'/g, '&#39;');

  const sendMessage = async () => {
    const text = elInput.value.trim();
    if (!text) return;
    elInput.value = '';
    elInput.focus();

    // render user
    makeBubble('user', escapeHtml(text));

    // typing
    showTyping();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId })
      });
      const data = await res.json();

      hideTyping();
      renderReply(data.reply);
      // store session context if server returns it
      if (data.session) {
        try { localStorage.setItem('rn_last_session', JSON.stringify(data.session)); } catch {}
      }
    } catch (e) {
      hideTyping();
      renderReply({ type: 'text', content: 'Sorry—network error.' });
    }
  };

  /* ---------- Open / Close ---------- */
  const openChat = () => {
    elChat.classList.remove('hidden');
    elLauncher.setAttribute('aria-expanded', 'true');
    elInput.focus();
    scrollToBottom(false);

    // First-time boot greeting (one-time call)
    if (!sessionStorage.getItem('rn_booted')) {
      sessionStorage.setItem('rn_booted', '1');
      // Ask server for the greeting by sending a silent "hi"
      showTyping();
      fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'hi', session_id: sessionId })
      })
        .then(r => r.json())
        .then(data => { hideTyping(); renderReply(data.reply); })
        .catch(() => { hideTyping(); renderReply({ type:'text', content: "Hi! I’m RealtyAI. Tell me city, property type, and budget (e.g., “3BR apartments in Galle under 80M”)." }); });
    }
  };

  const closeChat = () => {
    elChat.classList.add('hidden');
    elLauncher.setAttribute('aria-expanded', 'false');
  };

  elLauncher.addEventListener('click', () => {
    if (elChat.classList.contains('hidden')) openChat();
    else closeChat();
  });
  elClose.addEventListener('click', closeChat);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !elChat.classList.contains('hidden')) closeChat();
  });

  /* ---------- Input handlers ---------- */
  elSend.addEventListener('click', sendMessage);
  elInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  // Default suggestions
  suggestFor(null);
})();
