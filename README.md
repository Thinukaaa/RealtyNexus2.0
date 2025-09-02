RealtyNexus 2.0 — Modern Real-Estate Chatbot Demo 🏠🤖

Smarter property decisions, faster.
RealtyNexus 2.0 is a single-page Flask app with a built-in assistant (RealtyAI) that answers customer queries, shows suggested prompts, renders listing cards, and logs conversations — all backed by SQLite.

✨ Highlights

Elegant one-page site with a centered, animated chat modal

RealtyAI chatbot with:

Suggested prompt chips (Fees / Areas / Book a valuation)

Typing indicator, quick replies, retry state

Human-like tone, bulleted answers, emojis (sparingly)

Inline lead capture (name + phone/email) when intent is detected

Local persistence (resume chat after refresh)

Avatars, hover timestamps, a11y roles, focus rings, and aria-live

Data layer

SQLite schema for properties, investments, contacts, messages, FTS

Area/type synonyms to improve understanding

Seeder that bulk-generates ~500 diversified listings with images

API

POST /chat returns a friendly answer + optional chips + listing cards

Styling

Modern dark-blue palette: #0a173b #0f1c52 #17236a #71788f #eaf0f7

Capped bubble width (≈1/3 modal), responsive, high-contrast

🧱 Tech Stack

Backend: Python, Flask

Frontend: Vanilla HTML/CSS/JS

DB: SQLite (FTS5 for search)

LLM: Optional OpenAI (fallback to local composer if disabled)

📁 Project Structure
RealtyNexus2.0/
├─ app.py                    # Flask app (routes + chatbot orchestrator)
├─ db/
│  ├─ realty.db             # SQLite database (generated)
│  └─ schema.sql            # DDL
├─ nlp_slots.py             # Simple parser for intent/slots (city/type/budget)
├─ templates/
│  └─ index.html            # Single-page UI + modal chat
├─ static/
│  ├─ styles.css            # Styles (modal, cards, chips, bubbles)
│  ├─ app.js                # Chat UI behavior (typing, chips, cards, retry)
│  └─ img/
│     ├─ apartment.jpg
│     ├─ house.jpg
│     ├─ land.jpg
│     ├─ townhouse.jpg
│     └─ commercial.jpg
└─ scripts/
   ├─ init_db.py            # Apply schema.sql
   ├─ seed_kb_curated.py    # Curated KB (fees, hours, how-to, etc.)
   ├─ refresh_featured_summary.py  # Featured rollup → KB
   ├─ seed_listings.py      # BULK: ~500 listings + investments + synonyms
   └─ ls_counts.py          # Quick counts per table
   
🖌️ Theming & Assets

Palette: #0a173b, #0f1c52, #17236a, #71788f, #eaf0f7

Bubbles: max width ~⅓ of modal to keep messages scannable

Images: replace placeholders in static/img/ with your own photos

Favicon: inline SVG embedded to prevent 404s

♿ Accessibility & UX

Keyboard support: Tab/Enter/Esc

Focus rings + aria-* roles

High contrast (≥ 4.5:1)

prefers-reduced-motion respected (animations softened)

Typing indicator, “Jump to latest” pill when scrolled up, retry state


🤝 Contributing

PRs and issues are welcome. Keep changes small and documented.
Run scripts/ls_counts.py after seeding and include output in PRs that modify schema.

📄 License

MIT — see LICENSE.

🧾 Credits

Crafted for a rapid demo: Flask + SQLite + modern UI with a friendly, accurate assistant.
Questions? Ping RealtyAI in the chat or open an issue.
