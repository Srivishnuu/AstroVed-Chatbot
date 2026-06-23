from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from groq import Groq
import sqlite3, os, asyncio, httpx, re, secrets, hashlib, unicodedata
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv
from topic_map import TOPIC_MAP, match_topic  # ← this line stays

load_dotenv()

# ── Validate API key ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

SITE = "https://www.astroved.com"

# ── Handoff trigger keywords ───────────────────────────────────────────────────
HANDOFF_KEYWORDS = [
    'payment','pay','billing','bill','invoice','refund','subscription',
    'cancel','complaint','agent','human','team','speak to','talk to',
    'call me','confidential','account','order status','tracking',
    'delivery','not working','broken','urgent'
]

def needs_handoff(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in HANDOFF_KEYWORDS)

# ── Language detection ────────────────────────────────────────────────────────
def detect_language(text: str) -> str:
    """Detect if text is Tamil or English based on Unicode script."""
    tamil_chars = sum(1 for c in text if '\u0B80' <= c <= '\u0BFF')
    if tamil_chars > 0:
        return "tamil"
    return "english"

# ── TOPIC MAP ────────────────────────────────────────────────────────────────
# match_topic is imported from topic_map.py but we keep a local fallback too.
def match_topic(user_text: str):
    """Find the best-matching topic for the USER's message (not the bot's
    reply). Picks the topic whose matched keyword is the longest (most
    specific), so e.g. 'horoscope matching' beats plain 'horoscope'."""
    t = user_text.lower()
    best = None
    best_len = 0
    for key, info in TOPIC_MAP.items():
        for kw in info["keywords"]:
            if kw in t and len(kw) > best_len:
                best = key
                best_len = len(kw)
    return best

# ── Load knowledge base into searchable chunks ────────────────────────────────
def load_knowledge_base():
    chunks = []
    try:
        with open("knowledge_base.txt", "r", encoding="utf-8") as f:
            content = f.read()
        parts = re.split(r"\n--- PAGE: (.*?) \((https?://[^\)]+)\) ---\n", content)
        for i in range(1, len(parts) - 2, 3):
            title = parts[i].strip()
            url = parts[i + 1].strip()
            text = parts[i + 2].strip()
            if text:
                chunks.append({"title": title, "url": url, "text": text[:1500]})
        print(f"Loaded {len(chunks)} page chunks from knowledge base")
    except Exception as e:
        print(f"Could not load knowledge_base.txt: {e}")
    return chunks

KB_CHUNKS = load_knowledge_base()

def search_knowledge(query: str, top_k: int = 3):
    if not KB_CHUNKS:
        return ""
    query_words = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))
    if not query_words:
        return ""
    scored = []
    for chunk in KB_CHUNKS:
        haystack = (chunk["title"] + " " + chunk["text"]).lower()
        score = sum(1 for w in query_words if w in haystack)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c for _, c in scored[:top_k]]
    if not top_chunks:
        return ""
    result = ""
    for c in top_chunks:
        result += f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n"
    return result

def search_knowledge_for_url(url_fragment: str, top_k: int = 2):
    """Specifically pull KB chunks whose URL matches a known topic page."""
    if not KB_CHUNKS:
        return ""
    matches = [c for c in KB_CHUNKS if url_fragment in c["url"].lower()]
    if not matches:
        return ""
    result = ""
    for c in matches[:top_k]:
        result += f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n"
    return result

# ── System prompts ────────────────────────────────────────────────────────────
BASE_SYSTEM_PROMPT = """You are AstroVed.AI, a Vedic astrology assistant for AstroVed website.

RULES:
- Answer using the WEBSITE CONTENT provided below when relevant to the question
- Keep replies short: max 3-4 lines
- If user asks types/list/categories -> show short numbered list, wait for selection
- After selection -> explain in 3-4 lines only
- Be warm, mystical, helpful always
- If website content has a relevant product/page URL, mention you can share the link
- If no relevant website content given, answer using general Vedic astrology knowledge
- Never refuse a question
- Whenever you list the 12 zodiac/Moon signs, you MUST use the exact Tamil names below — never Sanskrit words like "Rashi: Mesha"

ZODIAC SIGNS IN TAMIL (format: "EnglishName (ராசி: TamilName)"):
1. Aries (ராசி: மேஷம்)
2. Taurus (ராசி: ரிஷபம்)
3. Gemini (ராசி: மிதுனம்)
4. Cancer (ராசி: கடகம்)
5. Leo (ராசி: சிம்மம்)
6. Virgo (ராசி: கன்னி)
7. Libra (ராசி: துலாம்)
8. Scorpio (ராசி: விருச்சிகம்)
9. Sagittarius (ராசி: தனுசு)
10. Capricorn (ராசி: மகரம்)
11. Aquarius (ராசி: கும்பம்)
12. Pisces (ராசி: மீனம்)

CONFIDENTIAL EXCEPTION:
If payment/billing/refund/account details asked -> say exactly:
'Let me connect you with our specialist team.' and stop."""

TOPIC_FORCE_INSTRUCTION = """

=== USER IS ASKING SPECIFICALLY ABOUT: {label} ===
You MUST answer using ONLY the content below about this exact topic. Give a
focused 3-4 line overview. Do NOT talk about zodiac signs, horoscopes, or any
other topic unless the content below is about that.

{content}

=== END TOPIC CONTENT ==="""

LANGUAGE_INSTRUCTIONS = {
    "tamil": (
        "\n\nMULTI-LANGUAGE RULE: The user has written in Tamil. "
        "You MUST reply ONLY in Tamil (தமிழ்). "
        "Do not mix English words unless it is a proper noun or a technical term "
        "that has no Tamil equivalent. Keep the same warm, mystical tone."
    ),
    "english": (
        "\n\nMULTI-LANGUAGE RULE: Reply in clear English."
    ),
}

# ── Keep-alive ────────────────────────────────────────────────────────────────
async def keep_alive():
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://astroved-chatbot.onrender.com/")
                print(f"Keep-alive ping OK status={r.status_code}")
        except Exception as e:
            print(f"Keep-alive failed (ok): {e}")
        await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(keep_alive())
    yield

app = FastAPI(lifespan=lifespan)
client = Groq(api_key=GROQ_API_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SQLite setup ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("chat.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role       TEXT,
            content    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id     TEXT PRIMARY KEY,
            user_name      TEXT,
            user_email     TEXT,
            user_phone     TEXT,
            status         TEXT DEFAULT 'bot',
            assigned_agent TEXT,
            issue_type     TEXT,
            priority       TEXT DEFAULT 'normal',
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE,
            password_hash TEXT,
            display_name  TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT role, content FROM messages
               WHERE session_id=? AND role IN ('user', 'assistant')
               ORDER BY created_at DESC LIMIT 20""",
            (session_id,)
        ).fetchall()
        conn.close()
        history = []
        for r, c in reversed(rows):
            if r in ("user", "assistant") and c and str(c).strip():
                history.append({"role": r, "content": str(c).strip()})
        return history
    except Exception as e:
        print(f"get_history error: {e}")
        return []

def save_message(session_id: str, role: str, content: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, role, content)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"save_message error: {e}")

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def seed_default_agents():
    conn = sqlite3.connect("chat.db")
    count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    if count == 0:
        default_agents = [
            ("agent1", "astroved123", "Support Agent 1"),
            ("agent2", "astroved123", "Support Agent 2"),
        ]
        for username, pw, name in default_agents:
            conn.execute(
                "INSERT INTO agents (username, password_hash, display_name) VALUES (?,?,?)",
                (username, hash_password(pw), name)
            )
        conn.commit()
        print("Seeded default agent accounts (CHANGE PASSWORDS IN PRODUCTION!)")
    conn.close()

init_db()
seed_default_agents()

# ── Request models ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_name: str = ""
    user_email: str = ""
    user_phone: str = ""

class HandoffRequest(BaseModel):
    session_id: str
    user_name: str = ""
    user_email: str = ""
    user_phone: str = ""
    issue_type: str = "general"
    priority: str = "normal"

class AgentLoginRequest(BaseModel):
    username: str
    password: str

class AgentReplyRequest(BaseModel):
    session_id: str
    agent_name: str
    message: str

class CloseSessionRequest(BaseModel):
    session_id: str

class SessionStartRequest(BaseModel):
    session_id: str
    user_name: str = ""
    user_email: str = ""
    user_phone: str = ""

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/session/start")
async def session_start(req: SessionStartRequest):
    try:
        conn = sqlite3.connect("chat.db")
        existing = conn.execute(
            "SELECT session_id FROM agent_sessions WHERE session_id=?", (req.session_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE agent_sessions
                   SET user_name=?, user_email=?, user_phone=?, updated_at=CURRENT_TIMESTAMP
                   WHERE session_id=?""",
                (req.user_name, req.user_email, req.user_phone, req.session_id)
            )
        else:
            conn.execute(
                """INSERT INTO agent_sessions
                   (session_id, user_name, user_email, user_phone, status)
                   VALUES (?,?,?,?, 'bot')""",
                (req.session_id, req.user_name, req.user_email, req.user_phone)
            )
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/users")
async def admin_users():
    conn = sqlite3.connect("chat.db")
    rows = conn.execute(
        """SELECT session_id, user_name, user_email, user_phone, status,
                  issue_type, created_at, updated_at
           FROM agent_sessions ORDER BY updated_at DESC"""
    ).fetchall()
    conn.close()
    return {"users": [
        {
            "session_id": r[0], "user_name": r[1], "user_email": r[2],
            "user_phone": r[3], "status": r[4], "issue_type": r[5],
            "created_at": r[6], "updated_at": r[7]
        }
        for r in rows
    ]}

# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        conn = sqlite3.connect("chat.db")
        row = conn.execute(
            "SELECT status FROM agent_sessions WHERE session_id=?",
            (req.session_id,)
        ).fetchone()
        conn.close()

        if row and row[0] == "with_agent":
            save_message(req.session_id, "user", req.message)
            return {"reply": None, "mode": "with_agent"}

        history = get_history(req.session_id)
        save_message(req.session_id, "user", req.message)

        # Auto-detect handoff need
        if needs_handoff(req.message):
            create_or_update_handoff(
                req.session_id, req.user_name, req.user_email,
                req.user_phone, "general", "normal"
            )
            reply = "I understand this needs special attention. Connecting you with our specialist team now — they'll be with you shortly! 🎧"
            save_message(req.session_id, "assistant", reply)
            return {"reply": reply, "mode": "handoff_triggered", "topic_url": None, "topic_label": None}

        # ── Language detection ────────────────────────────────────────────────
        detected_lang = detect_language(req.message)

        # ── Topic detection ───────────────────────────────────────────────────
        topic_key   = match_topic(req.message)
        topic_info  = TOPIC_MAP.get(topic_key) if topic_key else None
        topic_url   = topic_info["url"]   if topic_info else None
        topic_label = topic_info["label"] if topic_info else None

        # ── Build system prompt ───────────────────────────────────────────────
        # Start with base prompt + language instruction
        system_content = (
            BASE_SYSTEM_PROMPT
            + LANGUAGE_INSTRUCTIONS.get(detected_lang, LANGUAGE_INSTRUCTIONS["english"])
        )

        if topic_info:
            url_fragment = topic_info["url"].replace(SITE, "").strip("/").split("/")[0]
            kb_content = search_knowledge_for_url(url_fragment)
            if not kb_content:
                kb_content = search_knowledge(req.message, top_k=2)
            if not kb_content:
                kb_content = (
                    f"[Page: {topic_info['label']}]\n"
                    f"URL: {topic_info['url']}\n"
                    f"{topic_info.get('fallback','')}\n"
                )
            system_content += TOPIC_FORCE_INSTRUCTION.format(
                label=topic_info["label"], content=kb_content
            )
        else:
            relevant_content = search_knowledge(req.message, top_k=3)
            if relevant_content:
                system_content += (
                    f"\n\n=== RELEVANT WEBSITE CONTENT ===\n"
                    f"{relevant_content}\n"
                    f"=== END CONTENT ==="
                )

        # ── Build messages list ───────────────────────────────────────────────
        messages = [{"role": "system", "content": system_content}]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": str(req.message)})

        # ── Call Groq LLM ─────────────────────────────────────────────────────
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )

        reply = response.choices[0].message.content
        save_message(req.session_id, "assistant", reply)

        return {
            "reply": reply,
            "mode": "bot",
            "topic_url": topic_url,
            "topic_label": topic_label,
        }

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# ── Poll endpoint ─────────────────────────────────────────────────────────────
@app.get("/poll/{session_id}")
async def poll_session(session_id: str, since_id: int = 0):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT id, role, content FROM messages
               WHERE session_id=? AND id > ?
               ORDER BY id ASC""",
            (session_id, since_id)
        ).fetchall()
        status_row = conn.execute(
            "SELECT status, assigned_agent FROM agent_sessions WHERE session_id=?",
            (session_id,)
        ).fetchone()
        conn.close()

        new_messages = [{"id": r[0], "role": r[1], "content": r[2]} for r in rows]
        status = status_row[0] if status_row else "bot"
        agent  = status_row[1] if status_row else None

        return {"messages": new_messages, "status": status, "agent_name": agent}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Handoff ───────────────────────────────────────────────────────────────────
def create_or_update_handoff(session_id, name, email, phone, issue_type, priority):
    conn = sqlite3.connect("chat.db")
    existing = conn.execute(
        "SELECT session_id FROM agent_sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE agent_sessions SET status='waiting', issue_type=?, priority=?,
               updated_at=CURRENT_TIMESTAMP WHERE session_id=?""",
            (issue_type, priority, session_id)
        )
    else:
        conn.execute(
            """INSERT INTO agent_sessions
               (session_id, user_name, user_email, user_phone, status, issue_type, priority)
               VALUES (?,?,?,?,'waiting',?,?)""",
            (session_id, name, email, phone, issue_type, priority)
        )
    conn.commit()
    conn.close()

@app.post("/handoff")
async def handoff(req: HandoffRequest):
    try:
        create_or_update_handoff(
            req.session_id, req.user_name, req.user_email,
            req.user_phone, req.issue_type, req.priority
        )
        save_message(
            req.session_id, "system",
            f"Handoff requested: {req.issue_type} (priority: {req.priority})"
        )
        return {"status": "queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent login ───────────────────────────────────────────────────────────────
@app.post("/agent/login")
async def agent_login(req: AgentLoginRequest):
    try:
        conn = sqlite3.connect("chat.db")
        row = conn.execute(
            "SELECT display_name, password_hash FROM agents WHERE username=?",
            (req.username,)
        ).fetchone()
        conn.close()
        if not row or row[1] != hash_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return {"status": "ok", "display_name": row[0], "username": req.username}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: sessions ───────────────────────────────────────────────────────────
@app.get("/agent/sessions")
async def agent_sessions():
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT session_id, user_name, user_email, user_phone,
                      status, assigned_agent, issue_type, priority, updated_at
               FROM agent_sessions
               WHERE status IN ('waiting','with_agent')
               ORDER BY
                 CASE priority WHEN 'urgent' THEN 0 ELSE 1 END,
                 updated_at ASC"""
        ).fetchall()
        conn.close()
        sessions = []
        for r in rows:
            sessions.append({
                "session_id": r[0], "user_name": r[1], "user_email": r[2],
                "user_phone": r[3], "status": r[4], "assigned_agent": r[5],
                "issue_type": r[6], "priority": r[7], "updated_at": r[8]
            })
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: history ────────────────────────────────────────────────────────────
@app.get("/agent/history/{session_id}")
async def agent_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id ASC",
            (session_id,)
        ).fetchall()
        conn.close()
        return {"messages": [
            {"id": r[0], "role": r[1], "content": r[2], "time": r[3]} for r in rows
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: claim ──────────────────────────────────────────────────────────────
@app.post("/agent/claim/{session_id}")
async def agent_claim(session_id: str, agent_name: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute(
            """UPDATE agent_sessions
               SET status='with_agent', assigned_agent=?, updated_at=CURRENT_TIMESTAMP
               WHERE session_id=?""",
            (agent_name, session_id)
        )
        conn.commit()
        conn.close()
        save_message(session_id, "system", f"{agent_name} has joined the chat")
        return {"status": "claimed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: reply ──────────────────────────────────────────────────────────────
@app.post("/agent/reply")
async def agent_reply(req: AgentReplyRequest):
    try:
        save_message(req.session_id, "assistant", req.message)
        conn = sqlite3.connect("chat.db")
        conn.execute(
            "UPDATE agent_sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
            (req.session_id,)
        )
        conn.commit()
        conn.close()
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: close ──────────────────────────────────────────────────────────────
@app.post("/agent/close")
async def agent_close(req: CloseSessionRequest):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute(
            """UPDATE agent_sessions
               SET status='closed', updated_at=CURRENT_TIMESTAMP
               WHERE session_id=?""",
            (req.session_id,)
        )
        conn.commit()
        conn.close()
        save_message(req.session_id, "system", "Agent has ended this conversation")
        return {"status": "closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Enhanced Agent Dashboard ──────────────────────────────────────────────────
AGENT_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>AstroVed · Support Console</title>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
<style>
:root{
  --void:#06040F;--panel:#0E0B1E;--surface:#161230;--lift:#1E1A38;
  --gold:#C9A84C;--gold-l:#E8C97A;--gold-glow:rgba(201,168,76,.18);
  --purple:#6C5CE7;--purple2:#4A3580;--purple-glow:rgba(108,92,231,.2);
  --green:#22c55e;--red:#ef4444;--blue:#3b82f6;--cyan:#06b6d4;
  --text:#EDE8D8;--muted:rgba(237,232,216,.5);--faint:rgba(237,232,216,.15);
  --border:rgba(201,168,76,.14);--border2:rgba(108,92,231,.3);
  --font-d:'Cinzel',serif;--font-b:'Inter',sans-serif;
  --r:10px;--r2:16px;
  --transition:all .22s cubic-bezier(.4,0,.2,1);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-b);background:var(--void);color:var(--text);height:100vh;overflow:hidden;display:flex;flex-direction:column}
#star-canvas{position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.4}
#login-screen{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 50% 30%,rgba(108,92,231,.12) 0%,var(--void) 70%)}
.login-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);padding:40px 36px;width:360px;position:relative;overflow:hidden;box-shadow:0 32px 80px rgba(0,0,0,.7),0 0 0 1px rgba(108,92,231,.1);animation:cardIn .6s cubic-bezier(.34,1.56,.64,1)}
@keyframes cardIn{from{opacity:0;transform:translateY(30px) scale(.95)}to{opacity:1;transform:none}}
.login-card::before{content:'';position:absolute;top:-60px;left:50%;transform:translateX(-50%);width:200px;height:200px;border-radius:50%;background:radial-gradient(circle,rgba(108,92,231,.25) 0%,transparent 70%);pointer-events:none}
.login-logo{text-align:center;margin-bottom:28px}
.login-logo h1{font-family:var(--font-d);font-size:18px;color:var(--gold-l);letter-spacing:.1em}
.login-logo p{font-size:11px;color:var(--muted);margin-top:4px;letter-spacing:.05em}
.login-logo .orb{width:56px;height:56px;border-radius:50%;margin:0 auto 14px;background:linear-gradient(135deg,var(--purple),var(--purple2));display:flex;align-items:center;justify-content:center;font-size:24px;box-shadow:0 0 28px var(--purple-glow);animation:orbPulse 3s ease-in-out infinite}
@keyframes orbPulse{0%,100%{box-shadow:0 0 28px var(--purple-glow)}50%{box-shadow:0 0 48px rgba(108,92,231,.45)}}
.inp-group{margin-bottom:14px}
.inp-group label{display:block;font-size:10px;font-weight:600;color:var(--gold);letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px}
.inp-group input{width:100%;background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:var(--r);padding:11px 14px;color:var(--text);font-family:var(--font-b);font-size:13px;outline:none;transition:var(--transition)}
.inp-group input:focus{border-color:rgba(108,92,231,.6);background:rgba(108,92,231,.06);box-shadow:0 0 0 3px var(--purple-glow)}
.login-btn{width:100%;padding:12px;background:linear-gradient(135deg,var(--purple),var(--gold));border:none;border-radius:var(--r);color:#fff;font-family:var(--font-d);font-size:12px;font-weight:700;letter-spacing:.08em;cursor:pointer;margin-top:6px;transition:var(--transition);box-shadow:0 4px 20px rgba(108,92,231,.4)}
.login-btn:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(108,92,231,.55)}
.login-err{color:var(--red);font-size:11px;text-align:center;margin-top:10px;display:none}
#app{display:none;height:100vh;flex-direction:column;position:relative;z-index:1}
#app.show{display:flex}
#topnav{height:54px;background:rgba(14,11,30,.9);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:14px;flex-shrink:0;position:relative;z-index:10}
.nav-brand{font-family:var(--font-d);font-size:13px;color:var(--gold-l);letter-spacing:.08em;flex:1}
.nav-brand span{color:var(--muted);font-family:var(--font-b);font-size:11px;margin-left:8px;font-weight:400}
.nav-btn{padding:6px 16px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;letter-spacing:.04em;transition:var(--transition);font-family:var(--font-b);display:flex;align-items:center;gap:6px}
.nav-btn.analytics{background:rgba(6,182,212,.12);border-color:rgba(6,182,212,.4);color:#67e8f9}
.nav-btn.analytics:hover{background:rgba(6,182,212,.25);border-color:var(--cyan);transform:translateY(-1px)}
.nav-btn.analytics.active{background:rgba(6,182,212,.25);border-color:var(--cyan)}
.nav-btn.logout{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.35);color:#fca5a5}
.nav-btn.logout:hover{background:rgba(239,68,68,.22);border-color:var(--red)}
.agent-pill{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);border-radius:20px;padding:4px 12px;font-size:11px;color:#86efac;display:flex;align-items:center;gap:6px}
.agent-pill::before{content:'';width:6px;height:6px;background:var(--green);border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
#main-area{flex:1;display:flex;overflow:hidden;position:relative}
#sidebar{width:300px;border-right:1px solid var(--border);overflow-y:auto;background:var(--panel);flex-shrink:0;display:flex;flex-direction:column}
.sidebar-hdr{padding:14px 16px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--panel);z-index:2;display:flex;align-items:center;justify-content:space-between}
.sidebar-hdr h3{font-family:var(--font-d);font-size:11px;color:var(--gold);letter-spacing:.08em}
.queue-count{background:rgba(239,68,68,.2);border:1px solid rgba(239,68,68,.4);border-radius:20px;padding:2px 8px;font-size:10px;color:#fca5a5;font-weight:600}
.sess-empty{padding:28px 16px;text-align:center;color:var(--muted);font-size:12px}
.sess-empty .icon{font-size:28px;margin-bottom:8px;opacity:.4}
.sess-card{padding:13px 16px;border-bottom:1px solid rgba(255,255,255,.04);cursor:pointer;transition:var(--transition);position:relative;overflow:hidden}
.sess-card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:transparent;transition:var(--transition)}
.sess-card:hover{background:rgba(255,255,255,.03)}
.sess-card:hover::before{background:var(--gold)}
.sess-card.active{background:rgba(108,92,231,.1)}
.sess-card.active::before{background:var(--purple)}
.sess-row1{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.sess-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
.badge{font-size:9px;padding:2px 8px;border-radius:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.badge.waiting{background:rgba(239,68,68,.18);color:#fca5a5;border:1px solid rgba(239,68,68,.3)}
.badge.with_agent{background:rgba(34,197,94,.18);color:#86efac;border:1px solid rgba(34,197,94,.3)}
.sess-row2{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sess-time{font-size:9px;color:var(--faint);margin-top:3px}
#chat-panel{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--void)}
.chat-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:var(--muted)}
.chat-empty .big-icon{font-size:48px;opacity:.2;animation:float 4s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
.chat-empty p{font-size:13px}
#chat-hdr{padding:13px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;flex-shrink:0;background:rgba(14,11,30,.8);backdrop-filter:blur(12px)}
.chat-hdr-info{flex:1}
.chat-hdr-info h3{font-size:14px;font-weight:600;color:var(--text)}
.chat-hdr-info p{font-size:11px;color:var(--muted);margin-top:2px}
.hdr-action{padding:7px 16px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;transition:var(--transition);font-family:var(--font-b)}
.hdr-action.claim{background:rgba(34,197,94,.12);border-color:rgba(34,197,94,.4);color:#86efac}
.hdr-action.claim:hover{background:rgba(34,197,94,.25);transform:translateY(-1px)}
.hdr-action.end{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.35);color:#fca5a5}
.hdr-action.end:hover{background:rgba(239,68,68,.22);transform:translateY(-1px)}
#chat-body{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:10px;scrollbar-width:thin;scrollbar-color:var(--border) transparent}
#chat-body::-webkit-scrollbar{width:4px}
#chat-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.msg{max-width:68%;padding:10px 14px;border-radius:14px;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-word;animation:msgIn .2s ease-out}
@keyframes msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.user{align-self:flex-start;background:var(--lift);border:1px solid var(--border2);color:var(--text)}
.msg.assistant{align-self:flex-end;background:linear-gradient(135deg,var(--purple),var(--purple2));color:#fff}
.msg.system{align-self:center;background:none;color:var(--muted);font-size:10px;font-style:italic;max-width:100%;text-align:center;padding:4px 0}
.msg-meta{font-size:9px;color:rgba(255,255,255,.35);margin-top:3px}
.msg.user .msg-meta{text-align:left;color:var(--faint)}
#reply-bar{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center;background:rgba(14,11,30,.9);backdrop-filter:blur(12px);flex-shrink:0}
#reply-inp{flex:1;background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:24px;padding:10px 16px;color:var(--text);font-family:var(--font-b);font-size:13px;outline:none;transition:var(--transition)}
#reply-inp:focus{border-color:rgba(108,92,231,.5);background:rgba(108,92,231,.05)}
#reply-inp::placeholder{color:var(--faint)}
#reply-send{width:40px;height:40px;background:linear-gradient(135deg,var(--purple),var(--purple2));border:none;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:var(--transition);box-shadow:0 2px 14px var(--purple-glow)}
#reply-send:hover{transform:scale(1.1);box-shadow:0 4px 22px rgba(108,92,231,.55)}
#reply-send svg{width:16px;height:16px;fill:#fff;margin-left:2px}
#analytics-panel{position:absolute;inset:0;background:var(--void);z-index:5;overflow-y:auto;display:none;animation:slideIn .3s cubic-bezier(.4,0,.2,1)}
@keyframes slideIn{from{opacity:0;transform:translateX(30px)}to{opacity:1;transform:none}}
#analytics-panel.show{display:block}
.analytics-wrap{padding:28px;max-width:1100px;margin:0 auto}
.analytics-title{font-family:var(--font-d);font-size:20px;color:var(--gold-l);letter-spacing:.06em;margin-bottom:6px}
.analytics-sub{font-size:12px;color:var(--muted);margin-bottom:28px}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
.stat-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);padding:20px;position:relative;overflow:hidden;transition:var(--transition)}
.stat-card:hover{transform:translateY(-3px);box-shadow:0 12px 40px rgba(0,0,0,.5)}
.stat-card::after{content:'';position:absolute;top:-30px;right:-30px;width:100px;height:100px;border-radius:50%;opacity:.06;pointer-events:none}
.stat-card.c1::after{background:var(--purple)}
.stat-card.c2::after{background:var(--green)}
.stat-card.c3::after{background:var(--gold)}
.stat-card.c4::after{background:var(--cyan)}
.stat-icon{font-size:22px;margin-bottom:10px}
.stat-val{font-family:var(--font-d);font-size:28px;color:var(--text);line-height:1}
.stat-label{font-size:11px;color:var(--muted);margin-top:6px;font-weight:500}
.charts-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin-bottom:28px}
.chart-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);padding:20px}
.chart-card h4{font-size:12px;font-weight:600;color:var(--gold);letter-spacing:.06em;text-transform:uppercase;margin-bottom:18px}
.bar-chart{display:flex;flex-direction:column;gap:10px}
.bar-row{display:flex;align-items:center;gap:10px}
.bar-label{font-size:11px;color:var(--muted);width:80px;text-align:right;flex-shrink:0}
.bar-track{flex:1;height:8px;background:rgba(255,255,255,.06);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width 1s cubic-bezier(.4,0,.2,1)}
.bar-fill.p{background:linear-gradient(90deg,var(--purple),var(--gold))}
.bar-fill.g{background:linear-gradient(90deg,var(--green),var(--cyan))}
.bar-fill.o{background:linear-gradient(90deg,var(--gold),var(--red))}
.bar-val{font-size:11px;color:var(--text);width:28px;flex-shrink:0}
.donut-wrap{display:flex;align-items:center;gap:24px;justify-content:center;padding:10px 0}
.donut-svg{width:130px;height:130px;flex-shrink:0}
.donut-legends{display:flex;flex-direction:column;gap:10px}
.donut-leg{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted)}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.user-table-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);padding:20px;margin-bottom:28px}
.user-table-card h4{font-size:12px;font-weight:600;color:var(--gold);letter-spacing:.06em;text-transform:uppercase;margin-bottom:16px}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:var(--muted);font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
td{font-size:12px;color:var(--text);padding:10px 10px;border-bottom:1px solid rgba(255,255,255,.03)}
tr:hover td{background:rgba(255,255,255,.02)}
.td-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:9px;font-weight:700;text-transform:uppercase}
.td-badge.bot{background:rgba(108,92,231,.2);color:#c4b8ff}
.td-badge.waiting{background:rgba(239,68,68,.18);color:#fca5a5}
.td-badge.with_agent{background:rgba(34,197,94,.18);color:#86efac}
.td-badge.closed{background:rgba(255,255,255,.06);color:var(--muted)}
.activity-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);padding:20px}
.activity-card h4{font-size:12px;font-weight:600;color:var(--gold);letter-spacing:.06em;text-transform:uppercase;margin-bottom:14px}
.act-item{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.03)}
.act-dot{width:8px;height:8px;border-radius:50%;margin-top:4px;flex-shrink:0}
.act-content{flex:1}
.act-text{font-size:12px;color:var(--text)}
.act-time{font-size:10px;color:var(--muted);margin-top:2px}
.loading{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);padding:20px}
.spin{width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#toast{position:fixed;bottom:24px;right:24px;z-index:999;background:var(--lift);border:1px solid var(--border);border-radius:10px;padding:11px 18px;font-size:12px;color:var(--text);box-shadow:0 8px 32px rgba(0,0,0,.5);transform:translateY(20px);opacity:0;transition:var(--transition);pointer-events:none}
#toast.show{transform:none;opacity:1}
@media(max-width:900px){#sidebar{width:250px}.stat-grid{grid-template-columns:repeat(2,1fr)}.charts-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<canvas id="star-canvas"></canvas>

<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">
      <div class="orb">✦</div>
      <h1>AstroVed</h1>
      <p>SUPPORT CONSOLE · AGENT ACCESS</p>
    </div>
    <div class="inp-group"><label>Username</label>
      <input id="l-user" type="text" placeholder="agent1" autocomplete="username"/>
    </div>
    <div class="inp-group"><label>Password</label>
      <input id="l-pass" type="password" placeholder="••••••••" autocomplete="current-password"/>
    </div>
    <button class="login-btn" onclick="doLogin()">Enter the Console ✦</button>
    <div class="login-err" id="login-err">Invalid credentials — try again</div>
  </div>
</div>

<div id="app">
  <nav id="topnav">
    <div class="nav-brand">AstroVed <span>Support Console</span></div>
    <div class="agent-pill" id="agent-pill">Support Agent</div>
    <button class="nav-btn analytics" id="analytics-btn" onclick="toggleAnalytics()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M3 13h2v7H3v-7zm4-6h2v13H7V7zm4 3h2v10h-2V10zm4-7h2v17h-2V3zm4 4h2v13h-2V7z"/></svg>
      Analytics
    </button>
    <button class="nav-btn logout" onclick="doLogout()">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5-5-5zm-5 12H5V5h7V3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h7v-2z"/></svg>
      Log out
    </button>
  </nav>

  <div id="main-area">
    <div id="sidebar">
      <div class="sidebar-hdr">
        <h3>⚡ LIVE QUEUE</h3>
        <span class="queue-count" id="queue-count">0</span>
      </div>
      <div id="sess-list">
        <div class="sess-empty"><div class="icon">🌙</div><p>No chats waiting</p></div>
      </div>
    </div>

    <div id="chat-panel">
      <div id="chat-empty" class="chat-empty" style="display:flex">
        <div class="big-icon">✦</div>
        <p>Select a conversation from the queue</p>
      </div>
      <div id="chat-active" style="display:none;flex-direction:column;height:100%">
        <div id="chat-hdr">
          <div class="chat-hdr-info">
            <h3 id="hdr-name">—</h3>
            <p id="hdr-sub">—</p>
          </div>
          <button class="hdr-action claim" onclick="claimSession()">Claim Chat</button>
          <button class="hdr-action end" onclick="closeSession()">End &amp; Return to Bot</button>
        </div>
        <div id="chat-body"></div>
        <div id="reply-bar">
          <input id="reply-inp" placeholder="Type your reply…" onkeydown="if(event.key==='Enter')sendReply()"/>
          <button id="reply-send" onclick="sendReply()">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>
    </div>

    <div id="analytics-panel">
      <div class="analytics-wrap">
        <div class="analytics-title">✦ Dashboard Analytics</div>
        <div class="analytics-sub" id="analytics-ts">Loading live data…</div>
        <div class="stat-grid">
          <div class="stat-card c1"><div class="stat-icon">💬</div><div class="stat-val" id="st-total">—</div><div class="stat-label">Total Sessions</div></div>
          <div class="stat-card c2"><div class="stat-icon">✅</div><div class="stat-val" id="st-closed">—</div><div class="stat-label">Resolved Chats</div></div>
          <div class="stat-card c3"><div class="stat-icon">⏳</div><div class="stat-val" id="st-waiting">—</div><div class="stat-label">Waiting in Queue</div></div>
          <div class="stat-card c4"><div class="stat-icon">🤝</div><div class="stat-val" id="st-agent">—</div><div class="stat-label">With Agent Now</div></div>
        </div>
        <div class="charts-grid">
          <div class="chart-card">
            <h4>Top Issue Types</h4>
            <div class="bar-chart" id="issue-bars"><div class="loading"><div class="spin"></div>Loading…</div></div>
          </div>
          <div class="chart-card">
            <h4>Session Status Mix</h4>
            <div class="donut-wrap">
              <svg class="donut-svg" viewBox="0 0 42 42" id="donut-svg">
                <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="rgba(255,255,255,.06)" stroke-width="6"/>
              </svg>
              <div class="donut-legends" id="donut-legs"></div>
            </div>
          </div>
        </div>
        <div class="user-table-card">
          <h4>Recent Users</h4>
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Issue</th><th>Joined</th></tr></thead>
            <tbody id="user-tbody"><tr><td colspan="6"><div class="loading"><div class="spin"></div>Loading…</div></td></tr></tbody>
          </table>
        </div>
        <div class="activity-card">
          <h4>Recent Activity</h4>
          <div id="activity-feed"><div class="loading"><div class="spin"></div>Loading…</div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
(function(){
  const c=document.getElementById('star-canvas'),x=c.getContext('2d');let s=[];
  function sz(){c.width=innerWidth;c.height=innerHeight;}
  function mk(){s=Array.from({length:120},()=>({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*1.2+.2,a:Math.random(),da:(Math.random()*.002+.001)*(Math.random()<.5?1:-1)}))}
  function dr(){x.clearRect(0,0,c.width,c.height);s.forEach(p=>{p.a+=p.da;if(p.a>1||p.a<.1)p.da*=-1;x.beginPath();x.arc(p.x,p.y,p.r,0,Math.PI*2);x.fillStyle='rgba(210,200,170,'+p.a+')';x.fill();});requestAnimationFrame(dr);}
  window.addEventListener('resize',()=>{sz();mk();});sz();mk();dr();
})();

const API=window.location.origin;
let agentName='',activeSession=null,pollSess=null,pollList=null,showingAnalytics=false;

function toast(msg,ms=2800){
  const t=document.getElementById('toast');t.textContent=msg;
  t.classList.add('show');setTimeout(()=>t.classList.remove('show'),ms);
}

function doLogin(){
  const u=document.getElementById('l-user').value.trim();
  const p=document.getElementById('l-pass').value.trim();
  if(!u||!p)return;
  fetch(API+'/agent/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})
    .then(r=>{if(!r.ok)throw new Error();return r.json();})
    .then(d=>{agentName=d.display_name;sessionStorage.setItem('av_agent',agentName);enterApp();})
    .catch(()=>{document.getElementById('login-err').style.display='block';});
}
document.getElementById('l-pass').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});

function enterApp(){
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app').classList.add('show');
  document.getElementById('agent-pill').textContent=agentName;
  loadSessions();
  pollList=setInterval(loadSessions,5000);
}
function doLogout(){sessionStorage.clear();clearInterval(pollList);clearInterval(pollSess);location.reload();}
(function tryAuto(){const s=sessionStorage.getItem('av_agent');if(s){agentName=s;enterApp();}})();

function loadSessions(){
  fetch(API+'/agent/sessions').then(r=>r.json()).then(d=>{
    const list=document.getElementById('sess-list');
    document.getElementById('queue-count').textContent=d.sessions.length;
    if(!d.sessions.length){list.innerHTML='<div class="sess-empty"><div class="icon">🌙</div><p>No chats waiting</p></div>';return;}
    list.innerHTML='';
    d.sessions.forEach(s=>{
      const div=document.createElement('div');
      div.className='sess-card'+(s.session_id===activeSession?' active':'');
      div.onclick=()=>openSession(s);
      const who=s.user_name||'Anonymous';
      const t=s.updated_at?new Date(s.updated_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
      div.innerHTML=`<div class="sess-row1"><span class="sess-name">${who}</span><span class="badge ${s.status}">${s.status==='waiting'?'Waiting':s.assigned_agent||'Active'}</span></div><div class="sess-row2">${s.user_email||s.session_id.slice(0,18)}</div><div class="sess-time">${s.issue_type||'general'} · ${t}</div>`;
      list.appendChild(div);
    });
  }).catch(()=>{});
}

function openSession(s){
  activeSession=s.session_id;
  document.getElementById('chat-empty').style.display='none';
  const ca=document.getElementById('chat-active');ca.style.display='flex';
  document.getElementById('hdr-name').textContent=s.user_name||'Anonymous';
  document.getElementById('hdr-sub').textContent=(s.user_email||'')+(s.user_phone?' · '+s.user_phone:'');
  loadHistory();
  clearInterval(pollSess);pollSess=setInterval(loadHistory,3500);
  loadSessions();
  if(showingAnalytics)toggleAnalytics();
}

function loadHistory(){
  if(!activeSession)return;
  fetch(API+'/agent/history/'+activeSession).then(r=>r.json()).then(d=>{
    const body=document.getElementById('chat-body');
    if(!body)return;
    const atBot=body.scrollTop+body.clientHeight>=body.scrollHeight-40;
    body.innerHTML=d.messages.map(m=>{
      const t=m.time?new Date(m.time).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
      return`<div class="msg ${m.role}"><div>${(m.content||'').replace(/</g,'&lt;')}</div>${m.role!=='system'?`<div class="msg-meta">${t}</div>`:''}</div>`;
    }).join('');
    if(atBot)body.scrollTop=body.scrollHeight;
  }).catch(()=>{});
}

function claimSession(){
  if(!activeSession)return;
  fetch(API+'/agent/claim/'+activeSession+'?agent_name='+encodeURIComponent(agentName),{method:'POST'})
    .then(()=>{toast('Chat claimed ✓');loadHistory();loadSessions();});
}
function closeSession(){
  if(!activeSession)return;
  fetch(API+'/agent/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSession})})
    .then(()=>{activeSession=null;clearInterval(pollSess);document.getElementById('chat-active').style.display='none';document.getElementById('chat-empty').style.display='flex';toast('Session closed');loadSessions();});
}
function sendReply(){
  const inp=document.getElementById('reply-inp');
  const msg=inp.value.trim();if(!msg||!activeSession)return;
  inp.value='';
  fetch(API+'/agent/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSession,agent_name:agentName,message:msg})})
    .then(loadHistory);
}

function toggleAnalytics(){
  showingAnalytics=!showingAnalytics;
  const panel=document.getElementById('analytics-panel');
  const btn=document.getElementById('analytics-btn');
  panel.classList.toggle('show',showingAnalytics);
  btn.classList.toggle('active',showingAnalytics);
  if(showingAnalytics)loadAnalytics();
}

async function loadAnalytics(){
  document.getElementById('analytics-ts').textContent='Last updated: '+new Date().toLocaleTimeString();
  try{
    const [usersRes]=await Promise.all([fetch(API+'/admin/users').then(r=>r.json())]);
    const allSess=usersRes.users||[];
    const total=allSess.length;
    const closed=allSess.filter(s=>s.status==='closed').length;
    const waiting=allSess.filter(s=>s.status==='waiting').length;
    const withAgent=allSess.filter(s=>s.status==='with_agent').length;
    animCount('st-total',total);animCount('st-closed',closed);animCount('st-waiting',waiting);animCount('st-agent',withAgent);
    const issues={};
    allSess.forEach(s=>{const k=s.issue_type||'general';issues[k]=(issues[k]||0)+1;});
    const issueEntries=Object.entries(issues).sort((a,b)=>b[1]-a[1]).slice(0,6);
    const maxIssue=issueEntries[0]?issueEntries[0][1]:1;
    const colors=['p','g','o','p','g','o'];
    document.getElementById('issue-bars').innerHTML=issueEntries.map(([k,v],i)=>`<div class="bar-row"><div class="bar-label">${k}</div><div class="bar-track"><div class="bar-fill ${colors[i]}" style="width:0%" data-target="${Math.round(v/maxIssue*100)}%"></div></div><div class="bar-val">${v}</div></div>`).join('')||'<div style="color:var(--muted);font-size:12px;padding:10px 0">No data yet</div>';
    setTimeout(()=>{document.querySelectorAll('.bar-fill[data-target]').forEach(el=>{el.style.width=el.dataset.target;});},100);
    const statuses=[{label:'Bot',val:allSess.filter(s=>s.status==='bot').length,color:'#6C5CE7'},{label:'Waiting',val:waiting,color:'#ef4444'},{label:'With Agent',val:withAgent,color:'#22c55e'},{label:'Closed',val:closed,color:'#C9A84C'}].filter(s=>s.val>0);
    renderDonut(statuses,total||1);
    const recent=allSess.slice(0,10);
    document.getElementById('user-tbody').innerHTML=recent.length?recent.map(u=>`<tr><td>${u.user_name||'—'}</td><td>${u.user_email||'—'}</td><td>${u.user_phone||'—'}</td><td><span class="td-badge ${u.status}">${u.status}</span></td><td>${u.issue_type||'general'}</td><td>${u.created_at?new Date(u.created_at).toLocaleDateString():'—'}</td></tr>`).join(''):'<tr><td colspan="6" style="color:var(--muted);font-size:12px;padding:16px">No users yet</td></tr>';
    const dotColors={waiting:'#ef4444',with_agent:'#22c55e',closed:'#C9A84C',bot:'#6C5CE7'};
    document.getElementById('activity-feed').innerHTML=allSess.slice(0,8).map(s=>`<div class="act-item"><div class="act-dot" style="background:${dotColors[s.status]||'#6C5CE7'}"></div><div class="act-content"><div class="act-text">${s.user_name||'Anonymous'} — ${s.issue_type||'general'} · <span class="td-badge ${s.status}">${s.status}</span></div><div class="act-time">${s.updated_at?new Date(s.updated_at).toLocaleString():'—'}</div></div></div>`).join('')||'<div style="color:var(--muted);font-size:12px;padding:10px 0">No activity yet</div>';
  }catch(e){console.error(e);}
}

function animCount(id,target){
  const el=document.getElementById(id);let cur=0;
  const step=Math.max(1,Math.ceil(target/30));
  const iv=setInterval(()=>{cur=Math.min(cur+step,target);el.textContent=cur;if(cur>=target)clearInterval(iv);},30);
}

function renderDonut(statuses,total){
  const svg=document.getElementById('donut-svg');
  const legs=document.getElementById('donut-legs');
  const r=15.9,circ=2*Math.PI*r;let offset=0;
  const segs=statuses.map(s=>{const pct=s.val/total;const seg={...s,pct,dash:circ*pct,gap:circ*(1-pct),offset};offset+=circ*pct;return seg;});
  svg.innerHTML=`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="rgba(255,255,255,.06)" stroke-width="6"/>`+segs.map(s=>`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="${s.color}" stroke-width="6" stroke-dasharray="${s.dash.toFixed(2)} ${(circ-s.dash).toFixed(2)}" stroke-dashoffset="${(circ/4-s.offset).toFixed(2)}" style="transition:stroke-dasharray .8s"/>`).join('')+`<text x="21" y="21" text-anchor="middle" dominant-baseline="central" fill="#EDE8D8" font-size="7" font-weight="600">${total}</text><text x="21" y="27" text-anchor="middle" dominant-baseline="central" fill="rgba(237,232,216,.5)" font-size="3.5">total</text>`;
  legs.innerHTML=statuses.map(s=>`<div class="donut-leg"><div class="leg-dot" style="background:${s.color}"></div>${s.label} <strong style="color:var(--text)">${s.val}</strong></div>`).join('');
}
</script>
</body>
</html>"""

@app.get("/agent/dashboard", response_class=HTMLResponse)
async def agent_dashboard_page():
    return AGENT_DASHBOARD_HTML

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY),
        "knowledge_chunks_loaded": len(KB_CHUNKS),
        "topics_loaded": len(TOPIC_MAP),
    }