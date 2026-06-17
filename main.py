from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import sqlite3, os, asyncio, httpx, re, secrets, hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Validate API key ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

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

CONFIDENTIAL EXCEPTION:
If payment/billing/refund/account details asked -> say exactly:
'Let me connect you with our specialist team.' and stop."""

# ── Keep-alive ──────────────────────────────────────────────────────────────
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

# ── SQLite setup — ALL tables ──────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("chat.db")

    # Existing chat messages table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role       TEXT,
            content    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # NEW: agent_sessions — tracks handoff status per chat session
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id    TEXT PRIMARY KEY,
            user_name     TEXT,
            user_email    TEXT,
            user_phone    TEXT,
            status        TEXT DEFAULT 'bot',
            assigned_agent TEXT,
            issue_type    TEXT,
            priority      TEXT DEFAULT 'normal',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # NEW: agents — login table for support team members
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
    """Create default agent accounts if none exist (CHANGE THESE PASSWORDS!)."""
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

# ── Request models ─────────────────────────────────────────────────────────────
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

# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # Check if this session is already handed off to an agent
        conn = sqlite3.connect("chat.db")
        row = conn.execute(
            "SELECT status FROM agent_sessions WHERE session_id=?",
            (req.session_id,)
        ).fetchone()
        conn.close()

        if row and row[0] == "with_agent":
            # Session is with a human agent — just save the message, don't call AI
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
            return {"reply": reply, "mode": "handoff_triggered"}

        relevant_content = search_knowledge(req.message, top_k=3)
        system_content = BASE_SYSTEM_PROMPT
        if relevant_content:
            system_content += f"\n\n=== RELEVANT WEBSITE CONTENT ===\n{relevant_content}\n=== END CONTENT ==="

        messages = [{"role": "system", "content": system_content}]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": str(req.message)})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )

        reply = response.choices[0].message.content
        save_message(req.session_id, "assistant", reply)
        return {"reply": reply, "mode": "bot"}

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# ── Poll endpoint — frontend checks for agent replies ──────────────────────────
@app.get("/poll/{session_id}")
async def poll_session(session_id: str, since_id: int = 0):
    """Frontend calls this every 3 seconds to check for new agent messages."""
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
        agent = status_row[1] if status_row else None

        return {"messages": new_messages, "status": status, "agent_name": agent}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Handoff endpoint ────────────────────────────────────────────────────────────
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

# ── Agent login ──────────────────────────────────────────────────────────────
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

# ── Agent: list sessions waiting / active ──────────────────────────────────────
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

# ── Agent: get full chat history for a session ─────────────────────────────────
@app.get("/agent/history/{session_id}")
async def agent_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id ASC",
            (session_id,)
        ).fetchall()
        conn.close()
        return {"messages": [{"id": r[0], "role": r[1], "content": r[2], "time": r[3]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: accept/claim a session ───────────────────────────────────────────────
@app.post("/agent/claim/{session_id}")
async def agent_claim(session_id: str, agent_name: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute(
            "UPDATE agent_sessions SET status='with_agent', assigned_agent=?, updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
            (agent_name, session_id)
        )
        conn.commit()
        conn.close()
        save_message(session_id, "system", f"{agent_name} has joined the chat")
        return {"status": "claimed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Agent: send reply ────────────────────────────────────────────────────────────
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

# ── Agent: close session (hand back to bot) ─────────────────────────────────────
@app.post("/agent/close")
async def agent_close(req: CloseSessionRequest):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute(
            "UPDATE agent_sessions SET status='closed', updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
            (req.session_id,)
        )
        conn.commit()
        conn.close()
        save_message(req.session_id, "system", "Agent has ended this conversation")
        return {"status": "closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY),
        "knowledge_chunks_loaded": len(KB_CHUNKS)
    }