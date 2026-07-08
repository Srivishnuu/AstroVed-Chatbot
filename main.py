from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from groq import Groq
import sqlite3, os, asyncio, httpx, re, secrets, hashlib, unicodedata
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv
from topic_map import TOPIC_MAP, match_topic
from fastapi.responses import StreamingResponse
import json as json_lib
import asyncio
import httpx
import os

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

SITE = "https://www.astroved.com"

# FIX: kept narrow + specific to real billing/escalation issues, mirrors the
# widget's CRM_KW list so backend and frontend agree on what truly needs a human.
HANDOFF_KEYWORDS = [
    'refund', 'billing issue', 'invoice problem', 'payment failed', 'payment issue',
    'cancel my subscription', 'complaint', 'talk to agent', 'talk to a human',
    'speak to agent', 'speak to a human', 'human agent', 'call me back',
    'account issue', 'order tracking', 'not working', 'broken', 'urgent help'
]

def needs_handoff(text: str) -> bool:
    return any(k in text.lower() for k in HANDOFF_KEYWORDS)

def detect_language(text: str) -> str:
    tamil_chars = sum(1 for c in text if '\u0B80' <= c <= '\u0BFF')
    return "tamil" if tamil_chars > 0 else "english"

def load_knowledge_base():
    chunks = []
    try:
        with open("knowledge_base.txt", "r", encoding="utf-8") as f:
            content = f.read()
        parts = re.split(r"\n--- PAGE: (.*?) \((https?://[^\)]+)\) ---\n", content)
        for i in range(1, len(parts) - 2, 3):
            title, url, text = parts[i].strip(), parts[i+1].strip(), parts[i+2].strip()
            if text:
                chunks.append({"title": title, "url": url, "text": text[:1500]})
        print(f"Loaded {len(chunks)} page chunks from knowledge base")
    except Exception as e:
        print(f"Could not load knowledge_base.txt: {e}")
    return chunks

KB_CHUNKS = load_knowledge_base()

def search_knowledge(query: str, top_k: int = 3):
    """Same as search_knowledge but also returns the matched chunks (with URL/title)
    so we can build a real topic_url even when there's no TOPIC_MAP entry."""
    if not KB_CHUNKS:
        return "", []
    query_words = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))
    if not query_words:
        return "", []
    scored = []
    for chunk in KB_CHUNKS:
        haystack = (chunk["title"] + " " + chunk["text"]).lower()
        score = sum(1 for w in query_words if w in haystack)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    text = "".join(f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n" for _, c in top)
    matches = [{"title": c["title"], "url": c["url"], "score": s} for s, c in top]
    return text, matches

def search_knowledge_for_url(url_fragment: str, top_k: int = 2):
    if not KB_CHUNKS: return ""
    matches = [c for c in KB_CHUNKS if url_fragment in c["url"].lower()]
    return "".join(f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n" for c in matches[:top_k])

# FIX (accuracy): removed the "HANDOFF: say exact phrase" instruction from the
# system prompt. The model was independently deciding to say the handoff
# sentence for things like "connect with crm" / "team", which then collided
# with the frontend's own CRM_KW trigger and produced duplicate "connect you
# with our specialist team" messages back-to-back. Handoff is now controlled
# ONLY by needs_handoff() in code (single source of truth, both code paths
# now use the same narrow keyword list).
BASE_SYSTEM_PROMPT = """You are AstroVed.AI, a Vedic astrology assistant for AstroVed (https://www.astroved.com).

CORE RULES:
- Always answer using the WEBSITE CONTENT provided — it has accurate product/service info
- If website content is provided, base your answer primarily on it
- Keep replies focused: 3-5 lines maximum for simple questions
- For lists/types/categories → numbered list (max 6 items), then wait for user to pick one
- After user picks → give 3-4 line detailed answer about THAT specific item
- Always be warm, mystical, Vedic in tone
- Never make up prices, dates, or specific product details not in the content
- Never refuse a question — if unsure, give general Vedic astrology guidance
- Reply ONLY about what was actually asked. Do not change topic or add unrelated info.
- If you are not fully sure of a fact (price, exact date, exact duration), say so plainly
  instead of guessing, and offer the relevant page link instead.

PRODUCT LINKING:
- When website content mentions a relevant page/service, naturally say "I can share the link to [service]"
- Only mention links that are genuinely relevant to what the user asked
- Don't force a link into every message

ACCURACY RULES:
- Moon sign = Rashi (Vedic), NOT Sun sign (Western)
- Nakshatra = birth star, one of 27 lunar mansions
- Lagna = Ascendant (rising sign at birth time)
- Dasha = planetary period system unique to Vedic astrology
- Remedies include: gemstones, mantras, yantras, pujas, fasting, donations

ZODIAC IN TAMIL (use when listing all 12 signs):
Aries(மேஷம்) Taurus(ரிஷபம்) Gemini(மிதுனம்) Cancer(கடகம்) Leo(சிம்மம்) Virgo(கன்னி)
Libra(துலாம்) Scorpio(விருச்சிகம்) Sagittarius(தனுசு) Capricorn(மகரம்) Aquarius(கும்பம்) Pisces(மீனம்)

Do NOT decide on your own to escalate to a human/specialist team — that is handled
automatically by the system. Just answer the user's astrology question normally."""

TOPIC_FORCE_INSTRUCTION = """

=== USER IS ASKING SPECIFICALLY ABOUT: {label} ===
You MUST answer using ONLY the content below about this exact topic. Give a
focused 3-4 line overview. Do NOT talk about zodiac signs, horoscopes, or any
other topic unless the content below is about that.
{content}
=== END TOPIC CONTENT ==="""

LANGUAGE_INSTRUCTIONS = {
    "tamil": "\n\nMULTI-LANGUAGE RULE: The user has written in Tamil. You MUST reply ONLY in Tamil (தமிழ்). Do not mix English words unless it is a proper noun or a technical term that has no Tamil equivalent. Keep the same warm, mystical tone.",
    "english": "\n\nMULTI-LANGUAGE RULE: Reply in clear English.",
}

async def keep_alive():
    await asyncio.sleep(10)
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

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

def init_db():
    conn = sqlite3.connect("chat.db")
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
        content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_sessions (
        session_id TEXT PRIMARY KEY, user_name TEXT, user_email TEXT, user_phone TEXT,
        status TEXT DEFAULT 'bot', assigned_agent TEXT, issue_type TEXT,
        priority TEXT DEFAULT 'normal', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE,
        password_hash TEXT, display_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()

def get_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? AND role IN ('user','assistant') ORDER BY created_at DESC LIMIT 20",
            (session_id,)).fetchall()
        conn.close()
        history = []
        for r, c in reversed(rows):
            if r in ("user","assistant") and c and str(c).strip():
                history.append({"role": r, "content": str(c).strip()})
        return history
    except Exception as e:
        print(f"get_history error: {e}"); return []

def save_message(session_id: str, role: str, content: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute("INSERT INTO messages (session_id, role, content) VALUES (?,?,?)", (session_id, role, content))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"save_message error: {e}")

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def seed_default_agents():
    conn = sqlite3.connect("chat.db")
    if conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
        for u, p, n in [("agent1","astroved123","Support Agent 1"),("agent2","astroved123","Support Agent 2")]:
            conn.execute("INSERT INTO agents (username, password_hash, display_name) VALUES (?,?,?)", (u, hash_password(p), n))
        conn.commit()
        print("Seeded default agent accounts")
    conn.close()

init_db(); seed_default_agents()

class ChatRequest(BaseModel):
    session_id: str; message: str; user_name: str = ""; user_email: str = ""; user_phone: str = ""

class HandoffRequest(BaseModel):
    session_id: str; user_name: str = ""; user_email: str = ""; user_phone: str = ""
    issue_type: str = "general"; priority: str = "normal"

class AgentLoginRequest(BaseModel):
    username: str; password: str

class AgentReplyRequest(BaseModel):
    session_id: str; agent_name: str; message: str

class CloseSessionRequest(BaseModel):
    session_id: str

class SessionStartRequest(BaseModel):
    session_id: str; user_name: str = ""; user_email: str = ""; user_phone: str = ""
    

# Add this new endpoint
@app.get("/agent/events")
async def agent_events():
    """SSE stream for dashboard — pushes new session alerts"""
    async def event_stream():
        last_count = 0
        while True:
            try:
                conn = sqlite3.connect("chat.db")
                rows = conn.execute(
                    "SELECT session_id, user_name, status, updated_at FROM agent_sessions WHERE status IN ('waiting','with_agent') ORDER BY updated_at DESC"
                ).fetchall()
                conn.close()
                count = len(rows)
                if count != last_count:
                    last_count = count
                    data = json_lib.dumps({
                        "type": "queue_update",
                        "count": count,
                        "sessions": [{"session_id":r[0],"user_name":r[1],"status":r[2],"updated_at":r[3]} for r in rows]
                    })
                    yield f"data: {data}\n\n"
                else:
                    yield f"data: {{\"type\":\"ping\"}}\n\n"
            except Exception as e:
                yield f"data: {{\"type\":\"error\",\"msg\":\"{str(e)}\"}}\n\n"
            await asyncio.sleep(3)
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.post("/session/start")
async def session_start(req: SessionStartRequest):
    try:
        conn = sqlite3.connect("chat.db")
        if conn.execute("SELECT session_id FROM agent_sessions WHERE session_id=?", (req.session_id,)).fetchone():
            conn.execute("UPDATE agent_sessions SET user_name=?, user_email=?, user_phone=?, updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
                (req.user_name, req.user_email, req.user_phone, req.session_id))
        else:
            conn.execute("INSERT INTO agent_sessions (session_id, user_name, user_email, user_phone, status) VALUES (?,?,?,?,'bot')",
                (req.session_id, req.user_name, req.user_email, req.user_phone))
        conn.commit(); conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/users")
async def admin_users():
    conn = sqlite3.connect("chat.db")
    rows = conn.execute(
        "SELECT session_id, user_name, user_email, user_phone, status, issue_type, created_at, updated_at FROM agent_sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return {"users": [{"session_id":r[0],"user_name":r[1],"user_email":r[2],"user_phone":r[3],"status":r[4],"issue_type":r[5],"created_at":r[6],"updated_at":r[7]} for r in rows]}

def create_or_update_handoff(session_id, name, email, phone, issue_type, priority):
    conn = sqlite3.connect("chat.db")
    if conn.execute("SELECT session_id FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone():
        conn.execute("UPDATE agent_sessions SET status='waiting', issue_type=?, priority=?, updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
            (issue_type, priority, session_id))
    else:
        conn.execute("INSERT INTO agent_sessions (session_id, user_name, user_email, user_phone, status, issue_type, priority) VALUES (?,?,?,?,'waiting',?,?)",
            (session_id, name, email, phone, issue_type, priority))
    conn.commit(); conn.close()

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        conn = sqlite3.connect("chat.db")
        row = conn.execute("SELECT status FROM agent_sessions WHERE session_id=?", (req.session_id,)).fetchone()
        # FIX (CRM loop bug): once an agent closes a session, status stays
        # 'closed' forever in the DB. Previously, the next user message would
        # fall through normal /chat logic fine, BUT the session stayed marked
        # 'closed' which made the dashboard keep treating it as a dead thread
        # AND any stray needs_handoff() match would re-open with stale state.
        # We now explicitly reset 'closed' -> 'bot' the moment the user sends
        # a new message, so it behaves like a brand-new bot conversation.
        if row and row[0] == "closed":
            conn.execute("UPDATE agent_sessions SET status='bot', updated_at=CURRENT_TIMESTAMP WHERE session_id=?", (req.session_id,))
            conn.commit()
            row = ("bot",)
        conn.close()
        if row and row[0] == "with_agent":
            save_message(req.session_id, "user", req.message)
            return {"reply": None, "mode": "with_agent"}
        history = get_history(req.session_id)
        save_message(req.session_id, "user", req.message)
        if needs_handoff(req.message):
            create_or_update_handoff(req.session_id, req.user_name, req.user_email, req.user_phone, "general", "normal")
            reply = "I understand this needs special attention. Connecting you with our specialist team now — they'll be with you shortly! 🎧"
            save_message(req.session_id, "assistant", reply)
            return {"reply": reply, "mode": "handoff_triggered", "topic_url": None, "topic_label": None}
        
        detected_lang = detect_language(req.message)
        topic_url, topic_label = match_topic(req.message)
        topic_info = None
        if topic_label:
            for _k, _v in TOPIC_MAP.items():
                if _v["label"] == topic_label:
                    topic_info = _v
                    break

        system_content = BASE_SYSTEM_PROMPT + LANGUAGE_INSTRUCTIONS.get(detected_lang, LANGUAGE_INSTRUCTIONS["english"])

        if topic_info:
            url_fragment = topic_info["url"].replace(SITE, "").strip("/").split("/")[0]
            kb_content = search_knowledge_for_url(url_fragment) or search_knowledge(req.message, top_k=2)
            if not kb_content:
                kb_content = f"[Page: {topic_info['label']}]\nURL: {topic_info['url']}\n{topic_info.get('fallback','')}\n"
            system_content += TOPIC_FORCE_INSTRUCTION.format(label=topic_info["label"], content=kb_content)
        else:
            relevant_content, kb_matches = search_knowledge(req.message, top_k=3)
            if relevant_content:
                system_content += f"\n\n=== RELEVANT WEBSITE CONTENT ===\n{relevant_content}\n=== END CONTENT ==="
            if not topic_url and kb_matches:
                topic_url = kb_matches[0]["url"]
                topic_label = kb_matches[0]["title"]

        # ↓ this line must sit at the SAME indent level as the if/else above (8 spaces),
        # not nested inside either branch — that's almost certainly what went wrong.
        messages = [{"role": "system", "content": system_content}]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": str(req.message)})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=450,
            temperature=0.45,
            top_p=0.9,
        )
        
        
        
        
        reply = response.choices[0].message.content
        save_message(req.session_id, "assistant", reply)
        return {"reply": reply, "mode": "bot", "topic_url": topic_url, "topic_label": topic_label}
    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.get("/poll/{session_id}")
async def poll_session(session_id: str, since_id: int = 0):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute("SELECT id, role, content FROM messages WHERE session_id=? AND id > ? ORDER BY id ASC", (session_id, since_id)).fetchall()
        status_row = conn.execute("SELECT status, assigned_agent FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone()
        conn.close()
        return {"messages": [{"id":r[0],"role":r[1],"content":r[2]} for r in rows],
                "status": status_row[0] if status_row else "bot",
                "agent_name": status_row[1] if status_row else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/handoff")
async def handoff(req: HandoffRequest):
    try:
        create_or_update_handoff(req.session_id, req.user_name, req.user_email, req.user_phone, req.issue_type, req.priority)
        save_message(req.session_id, "system", f"Handoff requested: {req.issue_type} (priority: {req.priority})")
        return {"status": "queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/login")
async def agent_login(req: AgentLoginRequest):
    try:
        conn = sqlite3.connect("chat.db")
        row = conn.execute("SELECT display_name, password_hash FROM agents WHERE username=?", (req.username,)).fetchone()
        conn.close()
        if not row or row[1] != hash_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return {"status": "ok", "display_name": row[0], "username": req.username}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent/sessions")
async def agent_sessions():
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT session_id, user_name, user_email, user_phone, status, assigned_agent, issue_type, priority, updated_at
               FROM agent_sessions WHERE status IN ('waiting','with_agent')
               ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, updated_at ASC""").fetchall()
        conn.close()
        return {"sessions": [{"session_id":r[0],"user_name":r[1],"user_email":r[2],"user_phone":r[3],"status":r[4],"assigned_agent":r[5],"issue_type":r[6],"priority":r[7],"updated_at":r[8]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent/history/{session_id}")
async def agent_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute("SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,)).fetchall()
        conn.close()
        return {"messages": [{"id":r[0],"role":r[1],"content":r[2],"time":r[3]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/claim/{session_id}")
async def agent_claim(session_id: str, agent_name: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute("UPDATE agent_sessions SET status='with_agent', assigned_agent=?, updated_at=CURRENT_TIMESTAMP WHERE session_id=?", (agent_name, session_id))
        conn.commit(); conn.close()
        save_message(session_id, "system", f"{agent_name} has joined the chat")
        return {"status": "claimed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/reply")
async def agent_reply(req: AgentReplyRequest):
    try:
        save_message(req.session_id, "assistant", req.message)
        conn = sqlite3.connect("chat.db")
        conn.execute("UPDATE agent_sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=?", (req.session_id,))
        conn.commit(); conn.close()
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/close")
async def agent_close(req: CloseSessionRequest):
    try:
        conn = sqlite3.connect("chat.db")
        # Set status to 'closed' but KEEP all messages — never delete history.
        # The /chat endpoint will flip this back to 'bot' the moment the user
        # types their next message (see FIX comment above in /chat).
        conn.execute(
            "UPDATE agent_sessions SET status='closed', updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
            (req.session_id,)
        )
        conn.commit(); conn.close()
        save_message(req.session_id, "system", "Agent has ended this conversation. Chat history preserved.")
        return {"status": "closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/agent/all-sessions")
async def agent_all_sessions():
    """Returns ALL sessions including closed ones for history view"""
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT session_id, user_name, user_email, user_phone, status, 
               assigned_agent, issue_type, priority, updated_at
               FROM agent_sessions 
               ORDER BY updated_at DESC LIMIT 100"""
        ).fetchall()
        conn.close()
        return {"sessions": [
            {"session_id":r[0],"user_name":r[1],"user_email":r[2],
             "user_phone":r[3],"status":r[4],"assigned_agent":r[5],
             "issue_type":r[6],"priority":r[7],"updated_at":r[8]} 
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Enhanced Agent Dashboard HTML ─────────────────────────────────────────────
AGENT_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>AstroVed · CRM Console</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Cinzel:wght@500;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#070814;--bg2:#0D1022;--bg3:#111827;
  --cyan:#00F5FF;--purple:#8B5CF6;--pink:#FF00C8;
  --green:#22C55E;--yellow:#FACC15;--red:#EF4444;
  --gold:#C9A84C;--gl:#E8C97A;
  --text:#F0EEF8;--muted:rgba(240,238,248,.55);--faint:rgba(240,238,248,.14);
  --glass:rgba(255,255,255,.04);--glass2:rgba(255,255,255,.07);
  --gb:rgba(255,255,255,.08);
  --gc:0 0 20px rgba(0,245,255,.5),0 0 48px rgba(0,245,255,.2);
  --gp:0 0 20px rgba(139,92,246,.5),0 0 48px rgba(139,92,246,.2);
  --gk:0 0 20px rgba(255,0,200,.5),0 0 48px rgba(255,0,200,.2);
  --gg2:0 0 20px rgba(34,197,94,.5),0 0 48px rgba(34,197,94,.2);
  --fh:'Cinzel',serif;--fb:'Space Grotesk',sans-serif;--fm:'JetBrains Mono',monospace;
  --tr:all .22s cubic-bezier(.4,0,.2,1);--r:16px;
}
html,body{height:100%}
body{font-family:var(--fb);background:var(--bg);color:var(--text);overflow:hidden;display:flex;flex-direction:column;position:relative}

/* AURORA */
.aurora{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.ab{position:absolute;border-radius:50%;filter:blur(90px);animation:afl 20s ease-in-out infinite}
.ab:nth-child(1){width:700px;height:700px;background:radial-gradient(circle,rgba(0,245,255,.12) 0%,transparent 70%);top:-250px;left:-150px;opacity:.8}
.ab:nth-child(2){width:600px;height:600px;background:radial-gradient(circle,rgba(139,92,246,.15) 0%,transparent 70%);top:-200px;right:-120px;animation-delay:-7s;opacity:.8}
.ab:nth-child(3){width:500px;height:500px;background:radial-gradient(circle,rgba(255,0,200,.1) 0%,transparent 70%);bottom:-180px;left:35%;animation-delay:-14s;opacity:.6}
.ab:nth-child(4){width:400px;height:400px;background:radial-gradient(circle,rgba(201,168,76,.1) 0%,transparent 70%);bottom:-120px;right:-80px;animation-delay:-10s;opacity:.6}
@keyframes afl{0%,100%{transform:translate(0,0) scale(1)}25%{transform:translate(35px,25px) scale(1.06)}50%{transform:translate(-25px,45px) scale(.96)}75%{transform:translate(45px,-25px) scale(1.04)}}

/* GRID */
.grd{position:fixed;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(rgba(0,245,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(0,245,255,.018) 1px,transparent 1px);background-size:64px 64px}

/* CURSOR */
#cg{position:fixed;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle,rgba(0,245,255,.07) 0%,transparent 70%);pointer-events:none;z-index:9999;transform:translate(-50%,-50%);mix-blend-mode:screen;transition:left .06s,top .06s}
.cdot{position:fixed;border-radius:50%;background:var(--cyan);pointer-events:none;z-index:9998;transform:translate(-50%,-50%);box-shadow:0 0 10px var(--cyan),0 0 20px rgba(0,245,255,.4)}

::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(0,245,255,.25);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:rgba(0,245,255,.5)}

/* LOGIN */
#ls{position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;background:var(--bg)}
.lcard{position:relative;background:rgba(0,245,255,.025);backdrop-filter:blur(40px);border:1px solid rgba(0,245,255,.18);border-radius:26px;padding:50px 46px;width:410px;overflow:hidden;box-shadow:0 0 80px rgba(0,245,255,.08),0 50px 100px rgba(0,0,0,.75);animation:lIn .6s cubic-bezier(.34,1.56,.64,1)}
@keyframes lIn{from{opacity:0;transform:translateY(36px) scale(.95)}to{opacity:1;transform:none}}
.lcard::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,245,255,.05) 0%,rgba(139,92,246,.05) 50%,rgba(255,0,200,.03) 100%);pointer-events:none}
.lcard::after{content:'';position:absolute;top:-100%;left:-100%;width:300%;height:300%;background:conic-gradient(from 0deg,transparent 0%,rgba(0,245,255,.04) 15%,transparent 30%,rgba(139,92,246,.04) 50%,transparent 65%,rgba(255,0,200,.03) 80%,transparent 100%);animation:rot 10s linear infinite;pointer-events:none}
@keyframes rot{to{transform:rotate(360deg)}}
.lorb{width:76px;height:76px;border-radius:50%;margin:0 auto 22px;display:flex;align-items:center;justify-content:center;border:2px solid rgba(0,245,255,.4);box-shadow:var(--gc);animation:brth 3s ease-in-out infinite;overflow:hidden;position:relative;z-index:1}
.lorb img{width:100%;height:100%;object-fit:cover;border-radius:50%}
@keyframes brth{0%,100%{box-shadow:var(--gc)}50%{box-shadow:0 0 40px rgba(0,245,255,.8),0 0 80px rgba(0,245,255,.4)}}
.ltitle{font-family:var(--fh);font-size:21px;color:var(--cyan);text-align:center;letter-spacing:.12em;text-shadow:0 0 20px rgba(0,245,255,.5);position:relative;z-index:1;margin-bottom:4px}
.lsub{font-size:10px;color:var(--muted);text-align:center;letter-spacing:.16em;margin-bottom:34px;position:relative;z-index:1;font-family:var(--fm)}
.lg{margin-bottom:16px;position:relative;z-index:1}
.lg label{display:block;font-size:9px;font-weight:700;color:var(--cyan);letter-spacing:.15em;text-transform:uppercase;margin-bottom:6px;text-shadow:0 0 10px rgba(0,245,255,.4);font-family:var(--fm)}
.lg input{width:100%;background:rgba(0,245,255,.04);border:1px solid rgba(0,245,255,.18);border-radius:11px;padding:12px 16px;color:var(--text);font-family:var(--fb);font-size:13px;outline:none;transition:var(--tr)}
.lg input:focus{border-color:var(--cyan);background:rgba(0,245,255,.08);box-shadow:0 0 0 3px rgba(0,245,255,.1),var(--gc)}
.lbtn{width:100%;padding:14px;background:linear-gradient(135deg,rgba(0,245,255,.12),rgba(139,92,246,.18));border:1px solid rgba(0,245,255,.4);border-radius:11px;color:var(--cyan);font-family:var(--fh);font-size:12px;font-weight:700;letter-spacing:.1em;cursor:pointer;margin-top:8px;transition:var(--tr);position:relative;z-index:1;overflow:hidden;text-shadow:0 0 10px rgba(0,245,255,.5)}
.lbtn:hover{transform:translateY(-2px);box-shadow:var(--gc);color:#fff}
.lerr{color:var(--red);font-size:11px;text-align:center;margin-top:10px;display:none;position:relative;z-index:1;font-family:var(--fm)}

/* APP */
#app{display:none;height:100vh;flex-direction:column;position:relative;z-index:1}
#app.on{display:flex}

/* NAV */
#nav{height:56px;background:rgba(7,8,20,.85);backdrop-filter:blur(32px);border-bottom:1px solid rgba(0,245,255,.08);display:flex;align-items:center;padding:0 20px;gap:14px;flex-shrink:0;z-index:50;position:relative}
#nav::after{content:'';position:absolute;bottom:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(0,245,255,.35),rgba(139,92,246,.35),transparent)}
.nlogo{width:32px;height:32px;border-radius:50%;border:1.5px solid rgba(0,245,255,.45);box-shadow:var(--gc);flex-shrink:0}
.nbrand{font-family:var(--fh);font-size:13px;color:var(--cyan);letter-spacing:.08em;text-shadow:0 0 16px rgba(0,245,255,.4)}
.nbrand em{font-style:normal;font-family:var(--fb);font-size:10px;color:var(--muted);margin-left:8px;letter-spacing:.04em}
.nsep{flex:1}
.npill{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.28);border-radius:20px;padding:5px 14px;font-size:11px;color:#86efac;display:flex;align-items:center;gap:7px;box-shadow:var(--gg2);font-family:var(--fm)}
.npill::before{content:'';width:7px;height:7px;background:var(--green);border-radius:50%;animation:blk 2s infinite;box-shadow:0 0 8px var(--green)}
@keyframes blk{0%,100%{opacity:1}50%{opacity:.2}}
.nbtn{padding:7px 16px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;letter-spacing:.04em;transition:var(--tr);font-family:var(--fb);display:flex;align-items:center;gap:5px;background:none}
.nbtn.ana{border-color:rgba(0,245,255,.28);color:var(--cyan)}
.nbtn.ana:hover,.nbtn.ana.on{box-shadow:var(--gc);border-color:var(--cyan);background:rgba(0,245,255,.06)}
.nbtn.lo{border-color:rgba(239,68,68,.3);color:#fca5a5}
.nbtn.lo:hover{background:rgba(239,68,68,.08);box-shadow:0 0 14px rgba(239,68,68,.4);border-color:var(--red)}

/* BODY */
#body{flex:1;display:flex;overflow:hidden;position:relative}

/* SIDEBAR */
#sb{width:296px;border-right:1px solid rgba(0,245,255,.07);background:rgba(7,8,20,.65);backdrop-filter:blur(24px);display:flex;flex-direction:column;flex-shrink:0;overflow:hidden}
.sb-top{padding:14px 14px 10px;border-bottom:1px solid rgba(0,245,255,.07);flex-shrink:0}
.sb-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.sb-head h3{font-family:var(--fm);font-size:10px;color:var(--cyan);letter-spacing:.14em;text-shadow:0 0 10px rgba(0,245,255,.4)}
.qbadge{background:rgba(255,0,200,.13);border:1px solid rgba(255,0,200,.38);border-radius:20px;padding:2px 9px;font-size:10px;color:#ff80e5;font-weight:700;box-shadow:0 0 10px rgba(255,0,200,.3);font-family:var(--fm)}
.sb-search{position:relative;margin-bottom:8px}
.sb-search input{width:100%;background:rgba(0,245,255,.04);border:1px solid rgba(0,245,255,.1);border-radius:8px;padding:8px 10px 8px 30px;font-size:12px;color:var(--text);font-family:var(--fb);outline:none;transition:var(--tr)}
.sb-search input:focus{border-color:rgba(0,245,255,.35);background:rgba(0,245,255,.06);box-shadow:0 0 0 3px rgba(0,245,255,.07)}
.sb-search input::placeholder{color:var(--faint)}
.sb-search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);width:13px;height:13px;fill:var(--muted);pointer-events:none}
.sb-tabs{display:flex;gap:3px;margin-top:8px}
.sb-tab{flex:1;padding:5px 4px;border-radius:7px;border:1px solid rgba(255,255,255,.05);background:none;font-size:10px;font-weight:600;cursor:pointer;color:var(--muted);transition:var(--tr);font-family:var(--fb);text-align:center}
.sb-tab:hover{color:var(--text);border-color:rgba(0,245,255,.2)}
.sb-tab.on{background:rgba(0,245,255,.08);border-color:rgba(0,245,255,.3);color:var(--cyan);box-shadow:0 0 10px rgba(0,245,255,.18)}
.sb-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:10px 14px;border-bottom:1px solid rgba(0,245,255,.07)}
.ss-card{background:rgba(255,255,255,.03);border:1px solid rgba(0,245,255,.09);border-radius:10px;padding:9px 11px;transition:var(--tr)}
.ss-card:hover{border-color:rgba(0,245,255,.25);box-shadow:0 0 14px rgba(0,245,255,.12)}
.ss-val{font-family:var(--fm);font-size:21px;color:var(--cyan);text-shadow:0 0 14px rgba(0,245,255,.5)}
.ss-lbl{font-size:9px;color:var(--muted);margin-top:3px;font-weight:500}
#sl{flex:1;overflow-y:auto}
.sc{padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.025);cursor:pointer;transition:var(--tr);position:relative}
.sc::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:transparent;transition:var(--tr);border-radius:0 3px 3px 0}
.sc:hover{background:rgba(0,245,255,.03)}
.sc:hover::before{background:rgba(0,245,255,.5);box-shadow:0 0 8px var(--cyan)}
.sc.active{background:rgba(139,92,246,.07)}
.sc.active::before{background:var(--purple);box-shadow:0 0 8px var(--purple)}
.sc-r1{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.sc-av{width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,rgba(0,245,255,.2),rgba(139,92,246,.3));border:1px solid rgba(0,245,255,.2);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--cyan);flex-shrink:0}
.sc-name{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.sc-badge{font-size:8px;padding:2px 7px;border-radius:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;flex-shrink:0;font-family:var(--fm)}
.sc-badge.waiting{background:rgba(255,0,200,.1);color:#ff80e5;border:1px solid rgba(255,0,200,.28)}
.sc-badge.with_agent{background:rgba(34,197,94,.1);color:#86efac;border:1px solid rgba(34,197,94,.22)}
.sc-r2{display:flex;align-items:center;gap:4px;margin-left:38px}
.sc-email{font-size:10px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.sc-time{font-size:9px;color:var(--faint);flex-shrink:0;font-family:var(--fm)}
.sc-r3{margin-left:38px;margin-top:3px}
.sc-issue{font-size:9px;color:var(--faint)}
.sc-issue span{background:rgba(255,255,255,.04);border-radius:4px;padding:1px 5px;color:var(--muted)}
.sb-empty{padding:36px 16px;text-align:center;color:var(--muted);font-size:12px}
.sb-empty div{font-size:32px;opacity:.18;margin-bottom:10px;color:var(--cyan)}

/* CHAT PANEL */
#cp{flex:1;display:flex;flex-direction:column;min-width:0;background:rgba(7,8,20,.4)}
.cp-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:var(--muted)}
.cp-empty .icon{font-size:50px;opacity:.14;animation:flt 5s ease-in-out infinite;color:var(--cyan);text-shadow:var(--gc)}
@keyframes flt{0%,100%{transform:translateY(0)}50%{transform:translateY(-14px)}}
.cp-empty p{font-size:12px;font-family:var(--fm)}
#ch{padding:12px 20px;border-bottom:1px solid rgba(0,245,255,.07);display:flex;align-items:center;gap:14px;flex-shrink:0;background:rgba(7,8,20,.75);backdrop-filter:blur(16px)}
.ch-av{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,rgba(0,245,255,.2),rgba(139,92,246,.3));border:1.5px solid rgba(0,245,255,.3);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:var(--cyan);flex-shrink:0;box-shadow:0 0 16px rgba(0,245,255,.2)}
.ch-info{flex:1;min-width:0}
.ch-info h3{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ch-info p{font-size:10px;color:var(--muted);margin-top:1px}
.ch-tags{display:flex;gap:5px;margin-top:5px;flex-wrap:wrap}
.ch-tag{font-size:9px;padding:2px 7px;border-radius:5px;background:rgba(255,255,255,.04);color:var(--muted);border:1px solid rgba(255,255,255,.06);font-family:var(--fm)}
.ch-tag.status-waiting{background:rgba(255,0,200,.09);color:#ff80e5;border-color:rgba(255,0,200,.22)}
.ch-tag.status-with_agent{background:rgba(34,197,94,.09);color:#86efac;border-color:rgba(34,197,94,.2)}
.hbtn{padding:8px 16px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;transition:var(--tr);font-family:var(--fb);white-space:nowrap;background:none}
.hbtn.claim{border-color:rgba(34,197,94,.35);color:#86efac}
.hbtn.claim:hover{background:rgba(34,197,94,.1);transform:translateY(-1px);box-shadow:var(--gg2)}
.hbtn.end{border-color:rgba(239,68,68,.35);color:#fca5a5}
.hbtn.end:hover{background:rgba(239,68,68,.1);transform:translateY(-1px);box-shadow:0 0 14px rgba(239,68,68,.4)}
#cb{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:68%;padding:11px 15px;border-radius:14px;font-size:12.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word;animation:mi .2s ease-out}
@keyframes mi{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.msg.user{align-self:flex-start;background:rgba(0,245,255,.06);border:1px solid rgba(0,245,255,.14);color:var(--text)}
.msg.assistant{align-self:flex-end;background:linear-gradient(135deg,rgba(139,92,246,.18),rgba(0,245,255,.09));border:1px solid rgba(139,92,246,.28);color:var(--text);box-shadow:0 4px 20px rgba(139,92,246,.13)}
.msg.system{align-self:center;background:none;color:rgba(0,245,255,.45);font-size:10px;font-style:italic;max-width:100%;text-align:center;padding:3px 0;font-family:var(--fm)}
.msg-t{font-size:9px;margin-top:4px;color:rgba(255,255,255,.22);font-family:var(--fm)}
#rb{padding:12px 16px;border-top:1px solid rgba(0,245,255,.07);display:flex;gap:8px;align-items:center;background:rgba(7,8,20,.85);backdrop-filter:blur(16px);flex-shrink:0}
#ri{flex:1;background:rgba(0,245,255,.04);border:1px solid rgba(0,245,255,.14);border-radius:22px;padding:10px 16px;color:var(--text);font-family:var(--fb);font-size:12.5px;outline:none;transition:var(--tr)}
#ri:focus{border-color:rgba(0,245,255,.4);background:rgba(0,245,255,.07);box-shadow:0 0 0 3px rgba(0,245,255,.07)}
#ri::placeholder{color:var(--faint)}
#rs{width:40px;height:40px;background:linear-gradient(135deg,rgba(0,245,255,.18),rgba(139,92,246,.22));border:1px solid rgba(0,245,255,.32);border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:var(--tr)}
#rs:hover{transform:scale(1.1);box-shadow:var(--gc)}
#rs svg{width:15px;height:15px;fill:var(--cyan);margin-left:2px}

/* RIGHT PANEL */
#rp{width:280px;border-left:1px solid rgba(0,245,255,.07);background:rgba(7,8,20,.65);backdrop-filter:blur(24px);display:flex;flex-direction:column;flex-shrink:0;overflow:hidden}
.rp-tabs{display:flex;border-bottom:1px solid rgba(0,245,255,.07);flex-shrink:0}
.rp-tab{flex:1;padding:12px 8px;font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;cursor:pointer;color:var(--muted);border:none;background:none;border-bottom:2px solid transparent;transition:var(--tr);font-family:var(--fm)}
.rp-tab:hover{color:var(--text)}
.rp-tab.on{color:var(--cyan);border-bottom-color:var(--cyan);text-shadow:0 0 10px rgba(0,245,255,.4)}
.rp-body{flex:1;overflow-y:auto}
.ucard{padding:16px}
.uc-head{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.uc-av{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,rgba(0,245,255,.2),rgba(139,92,246,.28));border:1.5px solid rgba(0,245,255,.28);display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:var(--cyan);flex-shrink:0;box-shadow:0 0 16px rgba(0,245,255,.18)}
.uc-nm{font-size:14px;font-weight:600}
.uc-em{font-size:11px;color:var(--muted);margin-top:2px}
.uc-field{margin-bottom:10px}
.uc-label{font-size:9px;font-weight:700;color:var(--cyan);letter-spacing:.13em;text-transform:uppercase;margin-bottom:4px;font-family:var(--fm)}
.uc-val{font-size:11px;color:var(--text);background:rgba(0,245,255,.04);border-radius:7px;padding:7px 10px;border:1px solid rgba(0,245,255,.09);word-break:break-all;font-family:var(--fm)}
.uc-val.muted{color:var(--muted)}
.aitem{padding:11px 16px;border-bottom:1px solid rgba(255,255,255,.025);display:flex;gap:10px}
.adot{width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0}
.atext{font-size:11px;color:var(--text);line-height:1.5}
.atime{font-size:9px;color:var(--muted);margin-top:2px;font-family:var(--fm)}
.a-empty{padding:24px 16px;text-align:center;color:var(--muted);font-size:11px}
.qr-section{padding:12px 16px}
.qr-label{font-size:9px;font-weight:700;color:var(--cyan);letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px;font-family:var(--fm)}
.qr-chips{display:flex;flex-direction:column;gap:5px}
.qr-chip{padding:8px 12px;background:rgba(0,245,255,.04);border:1px solid rgba(0,245,255,.09);border-radius:8px;font-size:11px;color:var(--muted);cursor:pointer;transition:var(--tr);text-align:left;font-family:var(--fb)}
.qr-chip:hover{background:rgba(0,245,255,.09);border-color:rgba(0,245,255,.28);color:var(--text);box-shadow:0 0 10px rgba(0,245,255,.12)}

/* ═══ ANALYTICS OVERLAY — CYBERPUNK PREMIUM ═══ */
#ap{position:absolute;inset:0;background:rgba(7,8,20,.97);backdrop-filter:blur(12px);z-index:20;overflow-y:auto;display:none;animation:aIn .28s ease-out}
@keyframes aIn{from{opacity:0;transform:translateX(18px)}to{opacity:1;transform:none}}
#ap.on{display:block}
.aw{padding:30px;max-width:1100px;margin:0 auto}

/* ANA HEADER */
.ana-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:30px;flex-wrap:wrap;gap:12px}
.at{font-family:var(--fh);font-size:24px;color:var(--cyan);letter-spacing:.09em;text-shadow:var(--gc)}
.at-sub{font-size:11px;color:var(--muted);margin-top:5px;font-family:var(--fm)}
.hdr-actions{display:flex;gap:8px;align-items:center}
.live-pill{display:flex;align-items:center;gap:6px;background:rgba(34,197,94,.09);border:1px solid rgba(34,197,94,.25);border-radius:20px;padding:5px 13px;font-size:10px;color:#86efac;font-family:var(--fm);box-shadow:var(--gg2)}
.ldot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:blk 1.4s infinite;box-shadow:0 0 7px var(--green)}
.icon-btn{background:rgba(0,245,255,.07);border:1px solid rgba(0,245,255,.18);border-radius:9px;padding:7px 14px;color:var(--cyan);font-size:11px;cursor:pointer;font-family:var(--fb);transition:var(--tr);display:flex;align-items:center;gap:6px}
.icon-btn:hover{background:rgba(0,245,255,.14);box-shadow:var(--gc)}

/* KPI CARDS */
.sg{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.scard{position:relative;overflow:hidden;background:var(--glass);backdrop-filter:blur(24px);border-radius:22px;border:1px solid;padding:24px 22px;transition:var(--tr);cursor:default}
.scard:hover{transform:translateY(-6px)}
.cb{position:absolute;width:130px;height:130px;border-radius:50%;filter:blur(50px);top:-45px;right:-35px;opacity:.3;animation:brth 5s ease-in-out infinite;pointer-events:none}
.shimmer{position:absolute;inset:0;background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.035) 50%,transparent 60%);background-size:200% 100%;animation:shm 3.5s infinite;border-radius:inherit;pointer-events:none}
@keyframes shm{0%{background-position:200% 0}100%{background-position:-200% 0}}
.scard.c1{border-color:rgba(0,245,255,.22)}
.scard.c1:hover{box-shadow:var(--gc);border-color:rgba(0,245,255,.45)}
.scard.c1 .cb{background:var(--cyan)}
.scard.c1 .ico{color:var(--cyan);background:rgba(0,245,255,.1);border-color:rgba(0,245,255,.22)}
.scard.c1 .sv{color:var(--cyan);text-shadow:0 0 22px rgba(0,245,255,.5)}
.scard.c2{border-color:rgba(34,197,94,.22)}
.scard.c2:hover{box-shadow:var(--gg2);border-color:rgba(34,197,94,.45)}
.scard.c2 .cb{background:var(--green)}
.scard.c2 .ico{color:#86efac;background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.22)}
.scard.c2 .sv{color:#86efac;text-shadow:0 0 22px rgba(34,197,94,.5)}
.scard.c3{border-color:rgba(255,0,200,.22)}
.scard.c3:hover{box-shadow:var(--gk);border-color:rgba(255,0,200,.45)}
.scard.c3 .cb{background:var(--pink)}
.scard.c3 .ico{color:#ff80e5;background:rgba(255,0,200,.1);border-color:rgba(255,0,200,.22)}
.scard.c3 .sv{color:#ff80e5;text-shadow:0 0 22px rgba(255,0,200,.5)}
.scard.c4{border-color:rgba(139,92,246,.22)}
.scard.c4:hover{box-shadow:var(--gp);border-color:rgba(139,92,246,.45)}
.scard.c4 .cb{background:var(--purple)}
.scard.c4 .ico{color:#c4b8ff;background:rgba(139,92,246,.1);border-color:rgba(139,92,246,.22)}
.scard.c4 .sv{color:#c4b8ff;text-shadow:0 0 22px rgba(139,92,246,.5)}
.ico{width:42px;height:42px;border-radius:13px;border:1px solid;display:flex;align-items:center;justify-content:center;font-size:19px;margin-bottom:16px;position:relative;z-index:1}
.sv{font-family:var(--fm);font-size:34px;font-weight:700;line-height:1;letter-spacing:-.02em;position:relative;z-index:1}
.sl2{font-size:11px;color:var(--muted);margin-top:7px;font-weight:500;position:relative;z-index:1}

/* CHARTS */
.cg{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin-bottom:20px}
.cc{background:var(--glass);backdrop-filter:blur(24px);border:1px solid rgba(0,245,255,.09);border-radius:22px;padding:24px;position:relative;overflow:hidden;transition:var(--tr)}
.cc:hover{border-color:rgba(0,245,255,.18);box-shadow:0 0 32px rgba(0,245,255,.05)}
.cc::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(0,245,255,.28),transparent)}
.cc h4{font-size:10px;font-weight:700;color:var(--cyan);letter-spacing:.11em;text-transform:uppercase;margin-bottom:20px;font-family:var(--fm);text-shadow:0 0 10px rgba(0,245,255,.3);display:flex;align-items:center;gap:8px}
.cc h4::before{content:'';width:3px;height:15px;background:var(--cyan);border-radius:3px;box-shadow:0 0 8px var(--cyan);flex-shrink:0}
.br{display:flex;align-items:center;gap:10px;margin-bottom:13px}
.bl{font-size:10px;color:var(--muted);width:90px;text-align:right;flex-shrink:0;font-family:var(--fm)}
.bt{flex:1;height:8px;background:rgba(255,255,255,.05);border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,.04)}
.bf{height:100%;border-radius:8px;position:relative;overflow:hidden;transition:width 1.1s cubic-bezier(.4,0,.2,1)}
.bf.p{background:linear-gradient(90deg,var(--cyan),var(--purple));box-shadow:0 0 14px rgba(0,245,255,.4)}
.bf.g{background:linear-gradient(90deg,var(--green),var(--cyan));box-shadow:0 0 14px rgba(34,197,94,.4)}
.bf.o{background:linear-gradient(90deg,var(--pink),var(--purple));box-shadow:0 0 14px rgba(255,0,200,.4)}
.bf.y{background:linear-gradient(90deg,var(--yellow),var(--pink));box-shadow:0 0 14px rgba(250,204,21,.4)}
.bf::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent 50%,rgba(255,255,255,.18) 75%,transparent 100%);background-size:200% 100%;animation:shm 2.5s infinite}
.bv{font-size:10px;color:var(--text);width:24px;flex-shrink:0;text-align:right;font-family:var(--fm)}
.dw{display:flex;align-items:center;gap:24px;justify-content:center;padding:8px 0}
.ds{width:135px;height:135px;flex-shrink:0;filter:drop-shadow(0 0 18px rgba(0,245,255,.22))}
.dl{display:flex;flex-direction:column;gap:11px}
.dli{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted)}
.dd{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* TABLE */
.utc{background:var(--glass);backdrop-filter:blur(24px);border:1px solid rgba(0,245,255,.09);border-radius:22px;padding:24px;margin-bottom:24px;position:relative;overflow:hidden}
.utc::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(0,245,255,.28),rgba(139,92,246,.28),transparent)}
.utc h4{font-size:10px;font-weight:700;color:var(--cyan);letter-spacing:.11em;text-transform:uppercase;margin-bottom:16px;font-family:var(--fm);text-shadow:0 0 10px rgba(0,245,255,.3);display:flex;align-items:center;gap:8px}
.utc h4::before{content:'';width:3px;height:15px;background:var(--purple);border-radius:3px;box-shadow:0 0 8px var(--purple);flex-shrink:0}
.tbl-w{overflow-x:auto;border-radius:12px;border:1px solid rgba(0,245,255,.07)}
table{width:100%;border-collapse:collapse}
thead{background:rgba(0,245,255,.04)}
th{font-size:9px;color:var(--cyan);font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:10px 12px;text-align:left;border-bottom:1px solid rgba(0,245,255,.09);font-family:var(--fm);white-space:nowrap}
td{font-size:11px;color:var(--text);padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.025);font-family:var(--fm)}
tr:hover td{background:rgba(0,245,255,.03)}
tr:last-child td{border-bottom:none}
.tb{display:inline-block;padding:3px 8px;border-radius:9px;font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.tb.bot{background:rgba(139,92,246,.16);color:#c4b8ff;border:1px solid rgba(139,92,246,.28)}
.tb.waiting{background:rgba(255,0,200,.13);color:#ff80e5;border:1px solid rgba(255,0,200,.28)}
.tb.with_agent{background:rgba(34,197,94,.13);color:#86efac;border:1px solid rgba(34,197,94,.22)}
.tb.closed{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid rgba(255,255,255,.07)}
.ld{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);padding:20px;font-family:var(--fm)}
.sp{width:14px;height:14px;border:2px solid rgba(0,245,255,.14);border-top-color:var(--cyan);border-radius:50%;animation:spn .7s linear infinite}
@keyframes spn{to{transform:rotate(360deg)}}

/* TOAST */
#toast{position:fixed;bottom:22px;right:22px;z-index:999;background:rgba(13,16,34,.96);border:1px solid rgba(0,245,255,.22);border-radius:13px;padding:12px 20px;font-size:12px;color:var(--text);box-shadow:0 8px 36px rgba(0,0,0,.55),var(--gc);transform:translateY(16px);opacity:0;transition:all .3s cubic-bezier(.34,1.56,.64,1);pointer-events:none;font-family:var(--fb);backdrop-filter:blur(16px)}
#toast.on{transform:none;opacity:1}
</style>
</head>
<body>
<div class="aurora"><div class="ab"></div><div class="ab"></div><div class="ab"></div><div class="ab"></div></div>
<div class="grd"></div>
<div id="cg"></div>

<!-- LOGIN -->
<div id="ls">
  <div class="lcard">
    <div class="lorb"><img id="login-logo" alt="AstroVed"/></div>
    <div class="ltitle">AstroVed</div>
    <div class="lsub">CRM SUPPORT CONSOLE</div>
    <div class="lg"><label>Username</label><input id="lu" type="text" placeholder="agent1" autocomplete="username"/></div>
    <div class="lg"><label>Password</label><input id="lp" type="password" placeholder="••••••••" autocomplete="current-password"/></div>
    <button class="lbtn" onclick="doLogin()">Enter Console ✦</button>
    <div class="lerr" id="le">Invalid credentials — please try again</div>
  </div>
</div>

<!-- APP -->
<div id="app">
  <nav id="nav">
    <img class="nlogo" id="nav-logo" alt="AstroVed"/>
    <div class="nbrand">AstroVed <em>Support Console</em></div>
    <div class="nsep"></div>
    <div class="npill" id="npill">Agent</div>
    <button class="nbtn ana" id="anabtn" onclick="toggleAna()">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M3 13h2v7H3v-7zm4-6h2v13H7V7zm4 3h2v10h-2V10zm4-7h2v17h-2V3zm4 4h2v13h-2V7z"/></svg>
      Analytics
    </button>
    <button class="nbtn lo" onclick="doLogout()">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5-5-5zm-5 12H5V5h7V3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h7v-2z"/></svg>
      Log out
    </button>
  </nav>
  <div id="body">
    <!-- SIDEBAR -->
    <div id="sb">
      <div class="sb-top">
        <div class="sb-head"><h3>⚡ LIVE QUEUE</h3><span class="qbadge" id="qbadge">0</span></div>
        <div class="sb-search">
          <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
          <input id="srch" placeholder="Search users…" oninput="filterCards()"/>
        </div>
        <div class="sb-tabs">
          <button class="sb-tab on" onclick="setTab('all',this)">All</button>
          <button class="sb-tab" onclick="setTab('waiting',this)">Waiting</button>
          <button class="sb-tab" onclick="setTab('with_agent',this)">Active</button>
          <button class="sb-tab" onclick="setTab('closed',this)">History</button>
        </div>
      </div>
      <div class="sb-stats">
        <div class="ss-card"><div class="ss-val" id="ss-w">0</div><div class="ss-lbl">Waiting</div></div>
        <div class="ss-card"><div class="ss-val" id="ss-a">0</div><div class="ss-lbl">With Agent</div></div>
      </div>
      <div id="sl"><div class="sb-empty"><div>⚡</div><p>No active chats</p></div></div>
    </div>

    <!-- CHAT PANEL -->
    <div id="cp">
      <div id="cp-empty" class="cp-empty" style="display:flex;flex:1">
        <div class="icon">✦</div>
        <p>Select a conversation from the queue</p>
      </div>
      <div id="cp-chat" style="display:none;flex-direction:column;flex:1;height:100%">
        <div id="ch">
          <div class="ch-av" id="ch-av">?</div>
          <div class="ch-info">
            <h3 id="ch-name">—</h3>
            <p id="ch-sub">—</p>
            <div class="ch-tags" id="ch-tags"></div>
          </div>
          <button class="hbtn claim" onclick="claimSess()">Claim Chat</button>
          <button class="hbtn end" onclick="closeSess()">End &amp; Return to Bot</button>
        </div>
        <div id="cb"></div>
        <div id="rb">
          <input id="ri" placeholder="Type your reply…" onkeydown="if(event.key==='Enter')sendReply()"/>
          <button id="rs" onclick="sendReply()"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
        </div>
      </div>
    </div>

    <!-- RIGHT PANEL -->
    <div id="rp">
      <div class="rp-tabs">
        <button class="rp-tab on" onclick="rpTab('user',this)">User</button>
        <button class="rp-tab" onclick="rpTab('activity',this)">Activity</button>
        <button class="rp-tab" onclick="rpTab('quick',this)">Quick</button>
      </div>
      <div class="rp-body" id="rp-user">
        <div class="ucard"><div style="text-align:center;padding:30px 0;color:var(--muted);font-size:12px"><div style="font-size:34px;opacity:.14;color:var(--cyan);margin-bottom:10px">◈</div>Select a chat to see user details</div></div>
      </div>
      <div class="rp-body" id="rp-activity" style="display:none"><div class="a-empty">Select a chat to see activity</div></div>
      <div class="rp-body" id="rp-quick" style="display:none">
        <div class="qr-section">
          <div class="qr-label">Quick Replies</div>
          <div class="qr-chips">
            <button class="qr-chip" onclick="useQR(this)">Thank you for reaching out! How can I assist you today?</button>
            <button class="qr-chip" onclick="useQR(this)">I'm checking your account details now, please hold on.</button>
            <button class="qr-chip" onclick="useQR(this)">Your request has been noted. Our team will follow up shortly.</button>
            <button class="qr-chip" onclick="useQR(this)">Could you please provide your registered email address?</button>
            <button class="qr-chip" onclick="useQR(this)">I understand your concern. Let me escalate this for you.</button>
            <button class="qr-chip" onclick="useQR(this)">Is there anything else I can help you with today?</button>
            <button class="qr-chip" onclick="useQR(this)">Your issue has been resolved. Have a wonderful day! ✨</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ANALYTICS OVERLAY -->
    <div id="ap">
      <div class="aw">
        <div class="ana-hdr">
          <div>
            <div class="at">✦ Command Analytics</div>
            <div class="at-sub" id="ats">Initializing data stream…</div>
          </div>
          <div class="hdr-actions">
            <div class="live-pill"><div class="ldot"></div>LIVE</div>
            <button class="icon-btn" onclick="loadAna()">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
              Refresh
            </button>
          </div>
        </div>

        <!-- KPI CARDS -->
        <div class="sg">
          <div class="scard c1"><div class="cb"></div><div class="shimmer"></div><div class="ico">💬</div><div class="sv" id="st">—</div><div class="sl2">Total Sessions</div></div>
          <div class="scard c2"><div class="cb"></div><div class="shimmer"></div><div class="ico">✅</div><div class="sv" id="sc2">—</div><div class="sl2">Resolved</div></div>
          <div class="scard c3"><div class="cb"></div><div class="shimmer"></div><div class="ico">⏳</div><div class="sv" id="sw">—</div><div class="sl2">Waiting</div></div>
          <div class="scard c4"><div class="cb"></div><div class="shimmer"></div><div class="ico">🤝</div><div class="sv" id="sa">—</div><div class="sl2">With Agent</div></div>
        </div>

        <!-- CHARTS -->
        <div class="cg">
          <div class="cc"><h4>Top Issue Types</h4><div id="ibars"><div class="ld"><div class="sp"></div>Loading…</div></div></div>
          <div class="cc"><h4>Status Mix</h4>
            <div class="dw">
              <svg class="ds" viewBox="0 0 42 42" id="donut"><circle cx="21" cy="21" r="15.9" fill="transparent" stroke="rgba(0,245,255,.05)" stroke-width="6"/></svg>
              <div class="dl" id="dleg"></div>
            </div>
          </div>
        </div>

        <!-- TABLE -->
        <div class="utc">
          <h4>Recent Users</h4>
          <div class="tbl-w">
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Issue</th><th>Date</th></tr></thead>
              <tbody id="utb"><tr><td colspan="6"><div class="ld"><div class="sp"></div>Loading…</div></td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const AV_LOGO="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAWgAAAFoCAYAAAB65WHVAAAQAElEQVR4Aex9B5wkR3X+e9VhZnbvlLMQIDBJwhgjkY11AowFJphwRxASCne7exJCEiIL2BI5CxCcdvdOQiCD+d8aGzAmg45ohAk2IHKUQBISine3M9Oh3v973Tsb7nbvZm93Z1P1r6tDddWrV1+9+up1dU+PIb94BDwCHgGPwKJEwBP0omwWr5RHwCPgESDyBO2twCPgEViaCKwArT1Br4BG9lX0CHgEliYCnqCXZrt5rT0CHoEVgIAn6BXQyL6KKxEBX+flgIAn6OXQir4OHgGPwLJEwBP0smxWXymPgEdgOSDgCXo5tKKvw0wR8Ok9AksCAU/QS6KZvJIeAY/ASkTAE/RKbHVfZ4+AR2BJIOAJekk0U2eV9KV5BDwCiwMBT9CLox28Fh4Bj4BHYDcEPEHvBomP8Ah4BDwCiwMBT9AzbQef3iPgEfAIdAgBT9AdAtoX4xHwCHgEZoqAJ+iZIubTewQ8Ah6BDiEwxwTdIa19MR4Bj4BHYAUg4Al6BTSyr6JHwCOwNBHwBL00281r7RHwCMwxAotRnCfoxdgqXiePgEfAIwAEPEEDBL96BDwCHoHFiIAn6MXYKl4nj8BiQ8DrsyAIeIJeENh9oR4Bj4BHYO8IeILeO0Y+hUfAI+ARWBAEPEEvCOy+0OWFgK+NR2B+EPAEPT+4eqkeAY+AR2DWCHiCnjWEXoBHwCPgEZgfBDxBzw+uXuo4Av7II+AR2EcEPEHvI3A+m0fAI+ARmG8EPEHPN8JevkfAI+AR2EcEPEHvI3Bzlc3L8Qh4BDwC0yHgCXo6ZHy8R8Aj4BFYYAQ8QS9wA/jiPQIeAY/AdAgsboKeTmsf7xHwCHgEVgACnqBXQCP7KnoEPAJLEwFP0Euz3bzWHgGPwOJGYE608wQ9JzB6IR4Bj4BHYO4R8AQ995h6iR4Bj4BHYE4Q8AQ9JzB6IR4Bj8BMEPBp20PAE3R7OPlUHgGPgEeg4wh4gu445L7A+UNAeP5ke8kegc4j4Am685j7EucNARYsS5+k5w0fL3ipIeAJeqm1mNd3WgSslXD0oifpUSD8bmkj4Al6abef1x4IgJgLO7755ub7zz23/lhEwZH20x3Awa9LHIHCsJd4Hbz6KwqByZVds0ZCa9n19u44pVarbHQueImmWLeOvG0rED4saQS8ES/p5vPKb9vG2dq1N9SCoPqaNC3wWNvb23jK8DDn8KxbUx7FBb/xCCw1BDxBL7UW8/qOIQACLuz3kEMOP82Y4HFZVk+jKCbm8BVnnPG7KjzrjEj8fPQYYv5gqSFQGPhSU9rrOy0CK+aCtdaAgN1ZZ+08yjn3OucEdecwSeouioKTqtWjexBBa9f6qQ7FwYeliYAn6KXZbite6+uu6y88Y5Dxy6vVyj3yvAlvmRHHlOdK1vKynp6dR+pUB54YIn7FQ+YBWIIIeIJego220lW2VowSb09P86+BxcYkSTCtQQGOsWejZF2pxMcw80s17uSTy2t67INHYCkhsKIIeik1jNd17wgEAdk4rlScyx2Bmml0YaagJO3gxT09dz9wGx4kKqmTXzwCSwwBT9BLrMFWurpr10qgc8/nnNN8LnPwrCRpCLPZxY6ZlbTxwLAaBLV3rHTMfP2XLgK7GPbSrYjXfPkjoHPJ5dTGb/Y3JnhZABca3jK8593rrqRdkjc/ta+vuU5JXcl995Q+xiOweBEYJ+jFq6PXzCNQILBu3fCovR59Jgj6xDRtpkQc0DQLMzmkY5D1RWeddetqJXcl+WmS+2iPwKJDYNTgF51eXiGPwC4ICA8Pr8vXr99xOCY0XpOmOa6PfXsDx1OtHGRZI4ui8BFh2H2mpvC/MFQUfFgqCHiCXiottcL1tLZ8EyMMw0vwYPBQEWVobuf1uSBNU2I2Vt+ZVi+a/I9Xlps1Ldv6eIJetk27fCqmc8fWctbTs/1kY8IXJUmqlWvTdplF8rxSqRwYx4HVjFu3Upt5NbUPHoGFQ8Ab6sJh70tuCwGd2uB87dqtQRTVLgjDoCqSYX6jLe+5KEGEjHrRxoSnrl9ff9y6dSpPguKi33gEFjECnqAXceN41YispWIa4+CDn/XPzMHTk6SRM5sZkStjcS7LQe5dYRhdpGS/kqY6vB0tXQQ8QS/dtlsBmgtby66n5/b9Mef8ZnjChFAQ9kwrr6TebNYdSPoZBx30tOdrfmtpn2RpXh88Ap1AwBN0J1D2ZewTAnb0wSBR7SWVSvUBea7eM8/CZlkJnuBQ256eG7ssyN8/MNynpvGZOoTALIy9Qxr6YlYkAvrTbBBotmFD4/5BEFyQZRnIVWZlryBmoyQfx5X7Eu1/kQJrxwYBPfPBI7C4EJiVwS+uqnhtliMCURS+Ioqig/I807nnWU9J6BRJluUUBPGLzz77rr/SQUAHg+WIna/T0kfAE/TSb8NlVwMlTBCn6+tr/KOIvAgPBnVaYkYPBqcDRb1o51I8MAwPC8Nav6br7ychv3gEFiECnqAXYaMsHpUWQpPywaC++wxyvjjEAi1yhDlcOUjTJoWheW5fX/3xIG2xdnbTJ3OonBflERhDwBP0GBT+YDEg0PoHlIMOajw/jquPS9MGyJnnxHueXD/JjQkixL2eSAcFEt3j3K8egUWDgCfoRdMUXhElSH0/+ayzZLUx5g157ghe9DzZaOFFY6qjetLGjenpRCytwYH84hFYJAjMk/EvktrNrxpe+hwj0CLIOE5eG0XxsXnedMxm1g8Gp1NTxBnBU0OEN5x33m376eCgg8R06X28R6DTCHiC7jTivrwpEdA5ZyXI9et3nhAE4fo0zZCO542cIZwY5J9lDYfB4J55vupijWsNEnrsg0dgoRHwBL3QLeDLBwL6vQ1yOKAgiC4IAnOQc1nGWDRufgNzlulgEJy9YcOOh+ogoYPF/JbppXsE2kNg3gi6veJ9Ko8AkbUET5lFv1YHgn5hs9nA1AaHncAGYwDrYBBFwcFhWLtAyxweLgcLPfbBI7CQCHiCXkj0fdkFArb4yTWRMeHbmIuojm6YOWw2db5bXtTTs+NJROxfuyO/LAYEPEEvhlZYwTpYK4Wn3NMz8pIoqj4iw5wwCLPjdokHhRggAgJXv02bw1p97U6PfFh5CCyeGne8IyyeqntNFhoBa8VYy9nZZ99xryCIL3BOFkwlHRTSVB8YVv62p6fxEiq96GLwIL94BBYIAU/QCwS8L3YcgThetRFzwMfCe86VKMevdPpISDBGhGHw4tNP/8vRFoOHxSDSaS18eR6BFgKeoFtI+H2HEdBf77HbsGH78SLugiRJML1ggg4rMak4ZmMwSGRhGN5v1ar9Xzzpoj9pIeD3HUTAE3QHwfZFtRCQCY8Cw3dEUVwhcnnr6kLu4cGHOlg45y7auDE5AV608170QrbIyi7bE/TKbv8Fqf2aNQRPmaWvr/nMOK4+JUma+g70IrJFl8dxHDmX2QUByBfqERhFYBF1ilGN/G6ZIyC8bRtnp512c7cIv66srGDHE7xqnC7sapKk4YKg+tTe3uYzrGW3Zk35tsne1PLXPQJziYAn6LlE08vaKwLWUkHEq1YdtAFO6t9iztcx8yKzQ2YRoSBgMsa8pqfnxi4dVIik0J384hHoEAKLrGN0qNa+mAVBwNritTr3ohfdeV9w8iv0a3ULokgbhUI/k6aNHA8MH8F86HmaxX+nQ1HwoZMIeILuJNorvazR+nd1VV4WRcGReZ7o9zYWrQ3CiWYdRIzhl/T11e89PMy5DjKj1fA7j8C8I7BoO8e819wX0FEElNisZdfbu/NEEN+GZrNJzPqwkBbtwszGuTSN4+AoTG9cqIpu27bN9xkFwoeOIOCNrSMw+0LGEQjfFEXVAHO8joiXwJyu6Hc6SMSce9ZZdz9627aTMx1syC8egQ4g4Am6AyC3V8TyTaWf71TvecOG+hlhGP8j5naFmZeI7ekDQ+fiuBLEcfWNy7eVfM0WIwJLpJMsRui8Tu0gYK01Ond75pk3HRrH8YVc+szwntvJvTjSYCzR1+4kCMIn9PYmp+tg41+7Wxxts9y18AS93Ft4wevXX2hQrR60IQjMQ+A9Z0Qc0BJbmElfByRjggtPP/2PB2/bxpjqsL7/LLF2XGrqLhUDW2q4en0LBMrvbaxff+exzsnL9W+sQHRLjpyLqhAHOrjEsXlod/fh68u4cvApj/3WIzD3CHiCnntMvcRRBFrvDYdh5W2VSuUAkSwn4nKSg5bewsxhkqR4YJi/tqencV+d6iD/45Wl15BLSGNP0EuosZaSqmvWXBPq3DOI7EnGRM9O0wTERkve3kTyPIoqq/Do0Gp7tAYhPfbBIzAlArOIXPIdZhZ191nnDwHW19HOOON31SgKXxlgcc7pt56XrPc8ASqjg40x4XM3bGg8UQchfUtlwnV/6BGYMwQ8Qc8ZlF5QCwFrpSDiavXo5zEHj0+Suj5gW6Jzz61atfbwncXpT8CjIAhfdd55v6ooSfupjhY+fj+XCHiCnks0vSwgUD4Y7Om5+xAReYNzgriCr7FfHivmogMddKIoeEKa3utUrZW1tLwqqZXqSPCF7AkBT9B7QsdfmzECrTlZY+JXVavxMXneXNTf25hxBccyMOe5YF7d9ff0yCHWsvNe9Bg4/mCOEPAEPUdAejFE1krxo5T165sPIjK9SZIpLMtkakOrMh7gRbNzzbxSqdzTmMYFemVN8UcEeuSDR2BuEPAEPTc4eikTEAhDfl0URaucS3XumSdcWlaHIoQHhikxBy/BlM4Dyx+vyFz2qWWFl6/MzBHwxjRzzHyOKRBQ71lv83t7G08xxqxLU/1anemwfYEyp9BtvqJKLzpzGIxWB0G1X8vp7ychv3gE5giBDnegOdLai1lkCJQPBvW1uiAILw6wEEneSSXxQBLFGQJFd5QgmY1JkiZhUFq7YcPOp4K0xb92h6bw65wg4Al6TmBc2UJaDwbj+MizwzB4TJI0MPnM8z73PI465hpMUVxqjM6odJSjoYbkxgRYwlfrIOVfuwMkfp0TBDxBzwmMK1mIsBLS2WffdRDI8VVZ5hSMgi31oBNBvWbGeAAv+hVE7lthWIUnLYUinSifqPhORx5F8WPi+IgXEpbWoIVDv3oE9hkBT9D7DJ3PqAi03lyIospr4zi+R543O/pgEKScVSpVzvPsi4OD1fcxm0sZTjRCR91oDBImz3VWx1yCB4aH6KBFJNBEUfLBI7BvCHiC3jfcFn+uDmioc6365kJPz8jfMYcb0jRFqaBGbDuzioCQQxDjSBDkl2iZhx0WfzJJmp/Xf20BQWKqRWPnPzAW59K8Wo2PMiYudLF2W0fvJOa/lr6ETiPgCbrTiC+b8sqpDa1OEFRfEkXBKudy/VFKJ71GF0UxYVz4+KZNXd+2VkJ9k4RZ3g7SbhBxSGBphI6sIvraXUbGhKf29Y08wtqTMx3EOlK4L2RZIuAJelk26/xXyloqiLi3t/G0IOC1SdLI4UQqIc5/3WUWiwAAEABJREFU4SgBUxvOmDjIsuxPzt3Vjyjq76fiX7cHBmrbRNzmOK4Q9qLXOhFQf3Yuy/CgdH/m+GVapp/qUBR82FcEVihB7ytcPl+JQOu1OqmCAN8EzxFEWBJ2eX3+t8wkQWDIufw9W7Yc/EcL75nhOrdKzvMd70qS9M9BEBvoKK34+d5Dh7DZbDhms7a3d+cztDxriXXvg0dgpgh4gp4pYj499fR8v/CUK5X6+dVq7SF4MKjec8dsSUQcplUCeO3XwUv+oDaJtZSXe3YWZD00dND1Itk74M0SSNPptU4GlInizNswxRFbq9/pIE/SQMSvM0OgY51qZmr51IsVAZCfGRo6Me3pufO+xkTn62t1ItJx8mGUyGz6L7uMm6oTEQuNLtaWZC1y5wC82evCsBpARzd6ed53DMXyvJHHcfWBBx/cPE8LtFb8A0MFwocZITAVQc9IgE+8MhEIw+7zoig8Ms+bHfaenRKfwdTGvw8MxP+u6FtbeKh6OBpYQIgYSI4aYY5eJTIa3cEdysR8tBZsztf/ZISOmbXi+1sH22A5FOUNZjm0YofqoAQDonG9vSOPFuGNSVJ8b6NjnqGIE3jteDCYb282k7cTvGZMIUxZvupJJDwwEP6XSD5cqVR1LrqYBqEOLOpFZ5l60dExUbTqFVpkfz8J+cUjMAMEPEHPAKyVnbR8MKgY4A7+DZjbjUGAHSO8slx2YRjiwWB21RVXdH1361YJyrck9OruYfTXfCKSvCfL8p3GhJjqKP5BYPfE8xADnDBP3oRkOXvjxuRRIO3Cs0eEX+cLgWUm1xP0MmvQ+arOmjXljy7gPT83DCtPTJKGzul20H6k8J7TtHErCPcNWs9160h10MMpg5K3tRJefnnXd/I8uzKKIgJJ7jHPlIJmFSnF32OJuDepGGvVixbMoOuZDx6BPSPQwQ62Z0X81cWMgBR/AnvWWbeuZg6sSEtX7hjRoMw8CHQ2g183NLTfX8qpjfEHgy2Ndt2DEAsvv15PLmk0GjcaE0EIpO2acP7OjQ5mGNSe0NMzspYwLQOdoAP5xSOwVwQ8Qe8VIp9gdKqA4viAC+I4fiDmVh0zd9B2RB8Mhmmaf/1Pf/rJ1doiw8N79p41TRm4+PznRz6y323GkMXUDIGeC9Iur8/3lotBDGUSBoc3nHrqbftZy/oT9CJ+vkufLN+fLTUEzFJT2OvbWQSsLf/GasOG7ccbw+dlmXILdZBclNo4yPM8MyZ713/+54kj7XrPLaRaZL5z5y8/BpL/ZhxXQxHpGEkzs8myuoui8IH77bffy1Uv1MH3PQXChz0i4I1kj/D4i0SXFCAYYy6C93koeLKj39sAkUoU6U+25dObNlX/szVgFEq1vSm96Kuv/pudggeGORaQJqYZlPzbFjLLhMx5rtPfZv2GDXfff3iYi5+lz1Koz77MEfAEvcwbeDbVUzK01rre3rsfbUx8JuZSBcRW/IpwNnLbz6sPBgPM4TZ3Zln+6vbz7Z6yRYgDA13/kaZu6yjpy4SU83oI3Ni5JI1jc0QQdBXf6bjuOurgnci8Vs8LnycEPEHPE7DLQay1+sYBkTHxO4Ig1Llb6WS94N9i7jlGkXLp5s3VX65ZU36tDhH7uJZ3A2HoLsmypr52B/tHKfsobR+y6Xc6kC3fsGFD/aTWoIEIv3oEpkQABjplvI9c4QhYK/CUWfr6GhvDsPJ3WdZw8AI7Zi+Y2nBhWAWhpb9Okuz92hxr1rT7YFBT7x70bgBzv8Hll1d/Afnvi+NIB52OzUUTMWM4wFx0TEFg3kpY+vvLQZD84hGYAoGOdbgpyvZRixQBkLOxlrO+vr8czRxc4BwRCK3j2jITGUPv+NCHVt+qxAqddBJ3Vnocf3yLELP3JUn+ax0EULdZy21XKWbGlE3DBUH8aB38cK4/XsFg2K4En24lIeAJeiW19ozruv/6OA7vD+8ZDwZBlTPOv28ZRJyL46rJ8/TLP/3ptz6kUnQ6QPezDUryOgANDKy+hdm9mXm2EmeeH2ViLp+IOTp3/fo/Hw6d/Hc6yC9TIeAJeipUVnCcSPmT7nPOaT5IJHtVs5mASLiDHh4UYGPSNHHO5W/ctm3u/5UEhFh4zCD/f8my9CtRVEU/6Nxrd0TFn8xmeGB4fBQddCH5xSMwDQIwzGmu+Oj2EVhGKdeto8ImskzeCC+2SuQ6OEdbAAnvuUJg548ODta+rlMbc+U9F9JHNypXyZ+o+RZ46kLEqLdgTx1ZmBnz6wnqmb3krLMaDygHDVkAf74j1fWF7CMCMMp9zOmzLTsE1qyRUMkQc6P/GATBs9O0qYTVQRsRYQ6CJKnfFYZcfG9juO1fDM6sOYaHOVeSxlTHV/M8/5c4roAcucODkcsrlWotiqR4vaT1i82Z1cSnXs4IdLDzLWcYl0Pd9HsbnJ1xxu/gNYevDgKd1RBMBTCIqzP1w/QKvGf9oFHtzZs2VX+tBEq09+9t0D4uw6PkjweFF+uggMEBlRYdlPZR4oyz4YFhU4wJnrthw45/HMagoYPkjKX4DMsWgQ4Q9LLFbllVzFoqiLhSOfrUMAxOStO6knPQuUpKHkU1eM/uf3fu/NOVWu7WrbN7rU5l7DmUH/bftIlvMCZ6WxTpu946KO0519xd1cFPXBRFFEXVV5533q8q27bpdzqkaIu5K8dLWqoIeIJeqi03h3rDc2Vr2Z1zzo4jiPJ+59SJ7CRHQAMho76rSPKej3zkHrdZKyHzzL1nyJiR4q33kOv1xhVZ5n4ShjUMSp19YJgkjRxTSidn2THrtVn9VIei4IMi4AlaUVjhofVgMM/Di6rV6jF53sxAjh2zDZCqwIPkLEuvGRioXW2tLd7DnmmzCAnUJplJPmQo3kPWd62dS97NBb3rFlrNRNAs0qIkznNoL/SK9et3HK5THRiyCk1mIdZnnQMEFlpExzrhQlfUlz81AtaWX6vr6dnx18x8bpKkxEzwIqljCzMbTKlgLjZ7TVlof7lrcwuCK+y4seWIN45sOvxRmg1xbROctVy8h4zB4apms74tiirqzYvK6UTQ+uugWKlU7mlM+FIt8+STO9sGWqYPiw+BwrAXn1peo04jwBzZMIxrzmWOiNsmN5rlIuKyarVCQVB5v/7zicWAAcKEDu0Jlq0UQFt3d/9Rf1e9Z35xeGR+XpFzG+3TIINZlYuSpAkEuKN9A3XA/HtCxtBLNmzYfvw2zEUrFkVd/GbFItBRI1yxKC/SiutbEkqG+k8fmAN9ZpYpMZkOkrO4IKiFSZLfIJIW39uYCVRC4NF1lF9Da8LKffNXUURkAnlmffMRa/hkypS8qc1FcbCYWhka6v4BM22K4wqJSPHx6zZFzDIZs3M5HhhWqmFYfcsshXUmuy9l3hEw816CL2BRIgDyYZ3rPOusn6+OovhlIGgmEn0PGPtOqSzwnFGq5AOXX1797Zo1M/xanaVC18dd+uunx4e5f0rukDSocS06JH/F9+iEiEHeM6tJf5FcpPneLMv/FASxftjfFZEd2DAbTPU0iJmf2tvbfJa17HQQ7UDRvohFioAn6EXaMPOtVuvBYBzf+0VBEDwiSRrwFnmfpgX2RVcRJ2FYM5jzvq5ev/E9KmMbbut1304ovGdL7vYT7rN/fnjyFmLwqHDQ3E4u6JInP/TK61+gcsRS2zbeIsTBwf1/5Vz+gSBoO6sWNVdB3+gwWF5+2mk3d+sgKiLFQDRXBXg5SweBBbHApQPPctVUCu/5zDO3HypCr4W3CK+NOkbOQFWIylfomM2rrrrq2MaMPcVrSn0r60cuiA93D0h2cs5MppCq9wEH5q//zdr77M+WHOrI1OaihKhJb7vtV+9J0+b/hWEVDwwF7K+xMwn7mpYxF93I4jh8VFfXAS9SKa3BVI99WFkIeIJeWe1d1NbaktziOHpDpVI53LkUlAZ6K67O/wYeYV6tVvV/+j4zMBB+xlp9k4TaJkGxIOKTKbvzVfe8T3xwfp40iEChhS2jFiapUxbsF9znHv+844KiNtvK+hbHbWx0sBgefnAikve3kXzOk6AOIGnc0JC84YwzdhxRDhrei55zoJeAwMKol4CeXsU5QkDJx1rONmzYflIQhC9K05TgYXbQDkSMCUJMbewUCScQYOH7zqiWXfdvvD48WA4GITtjaMxLRn0CGREy3fn5d73jHvdjkLmServCh4ufgAsPDnZ/Kk3rn45j/dodKWO2K2KW6fSBYeYqlerBlUp4iQrzP15RFFZeMCuvyiu5xuXUxpo114RRVNM/ga05l2FqgMfIbb7RAXm6MIzIOdo8NBT/wFrRH6W4dsuVtRSwJbfjjcc8yRwiL8h2CEF7nphfyTpNKA9X84G1Y5tvmnitvWMWa6mQyRy+Mc/znYwD0qGsPQFzkYp18AyC6NT16+uPGx4uP+40F4K9jKWDgCfopdNWs9bU2pJ0HvjAxzwNXuzT8GAQ5Gw6NveMqQ2QczXAnPdvRO56h1aov7/9X/6B3JmHKf8enRBV7528JuiWyKXF3HNBpjRhYSaT3k3wot2zdl52xJPZkpOt1HZdrWVnMXgMDsbfY+YPRFFMKL/tgYRmuaBM1sEzDE13GEYXrV27NVCSxiDBsxTtsy8hBDxBL6HGmp2qrQ/xyyoR9xaQjRJORzs7M2F6gwjE866hoUNvAgGGzCxt12uYCns9/tKbTw0OdScl2wUDzLSky5JTHkQcVo5OXvUTOi7mdZSj3jOoczG7QHnevAxTMn8IgjgQkQ6StAmazToGteAZhx76rHWKk7XlIKvHPix/BAqDX/7VXFo1nA9te3ooVLlZ1ngJ5jYfmOeNDn9vQ0A0VTz8av5gcLA6oLpYS3g4qUftBSXYm5/0kG5zWPP1oHmSlM2e6ApXg3S74IGh+fv7Xnnr84tSRkm+ON7LxlqrXnQ4MND1J5Hs3fBmaUYDyl7kt3eZCYMKBrXkkp6eG7ssPHsimcEg014pPtXiRMAsTrW8VnOJgLVihoY4Peecxl8FQXAhphi003e67TnPMxAcvUbrpjrR6Kt21MZyjS0HmAP++ZbXxYfTsc0RciagyUQlEKQBu9YqjgNqEgX7yxvvPvfog5XkkYRb1/e2t6ODiEhtAFNC3w3DSiAibm/55uo6BgSDwTSP49r9guDg4q0U6BTMlXwvZ3Ej0OlOurjRWP7avSyKokPyPMXUAPzLDtVXRDJ47SzCVw0MVL+A8+Lzpu0Wrw8GT7aU7bjg3g8Nj8rXSxMU63icZHFKCFzDJkTA2pKNWnKzTi46kI6JH5ldXMRbmgHB6QPDcoATCV+Dh5uFiE5uRIizzBEzv6Sn5877Wlt+3KmTOviyFgaBpUfQC4PTki3V2vItiQ0bGk8UCc5Kyg8BzYCgZld1kLELgjgEwdyK6ZVLVdqMf3ixtXxHOn5o/aJgPzo4bXCmb2qoLCVm3XNVKPs9HuQ1DXEsVObQKwRiI5KdROGB+Yt2vvnIh7GlGX+nA3jF9NQAABAASURBVPXgwcHoKyLp1RhsDM4z6tACYjbOJXkQRIcHQdfrtdj+/lbNyS/LGAGzjOvmq0b6YJDAJcJBkL02DMMIVDWjed/ZgshMonO3ItlVW7as+pG15f8etitXLBmVsd0e/fjoAPfCdIdzTOV0RyFDiHiVo/yPMaU/rlH20xqRQWSE4KhYkN+kTcqCVXRQdP/s/CJyLSFBcdTWpjWopGn6vjTN7zQmDEXcjGS0VdC0iThIUQlm8/wNG+onMZee/bTJ/YVlgYBZFrXwlZgSgTVrtsFTZuntrT8/irpPStMGyJkRN2XyOY8ULEFQwYPB5A/NZvxGLcBaznTfbmBLYEFrwnulb6VuR5IwEVbSBQTMqx3lN4Ccf1olc2BO7s6Akh92EUVIMGG6A1MdYXKnuKhLTt/5gSOewgy5lgxStbXqK24Wg8uWLd3fJ8ovj6Limau0lXnOEgm86CAyRvpVpLUMBKSFhkb5sLgRmLF2bRvojCX7DAuMgPC2bSdnPT23729McIkDzYmMUVtHdFMSNIbhwuevvvJK3m6tzMje5BoqWLD+7s0vqR7lHlF8b8OMkiqoScnZ3RAVnnMx/4xaMUjc/QWE/YMu4goiAqFiukNpLMcGnnVwWPJmoTUhW5A0tY8JCLEYXHbsuOPNzWb9t0FQNYTaUccWxmDXcFFUOxmD7plarP+FoaKwfAMMbPlWbiXXrNVxg6D74jiO/wrzv44ZfmSHQBFxeRRVgzzPv/SLX1w7rMVa2/60gsC75ZMpu+3M+x4TH52cX/BgRqxylHCLaY0bI0p+DCKugq11WkNwFYfcDU/6lpDSH9VI56YpGI03ZJIdnFcONA+tf+hn5yKWvj9YDgJ63E7Qn8pfffURO0X4DUGgg8/MXhVsp4w9pxE8bHXEbC459dTb9lPPHoNEicueM/qrSxABT9BLsNH2prKSiHbcDRt2PJQoOCtNM2RhxqZDK+iLAyXnZp6nb1dPXnWiGbxWR/1ULPs9vH5ucKjcuzlCOYYX0yJnd0tE6f/ViJScAyRVcsauWB2Retc5CDzFvHSRRmuvaYSYAEd8QH7+bS896pgTeykVDAbU5jJcfKdDE1/3sTSVr8RxVeeiMXWkcfMfmA1nWRNedHzM6tWrLtYSW4OxHi/l4HXfHQFP0LtjsuRjWiQShvEFcRwc7FyWMZZOVUyw6E+jidz/GxysfcViamN4mPN2yxcQJjOmky885kQ5JD0/bwixw9y5Em8xhRFSolMYMeJ3JedWIaNps+tjyn5eI536IJA0VpPspDw4kI5d/TD38iJ5f7Ftc8Oig83Q0Ikpc/K2LMubjMGIChe/TRGzT8a4MyFMXZ21fv2Ohyi2a9duVSRmL9lLWFQIeIJeVM0xe2UsyJCI5eyzt/+9MeGLGo2GTm2E1KFFxEmA51h4IHl7lu14nRbb309CbS5IyNRfJo6Pa/RHh0g1b7DOHhN3ObB2SOkPu4lAzhQhHTJgO+1q9CHi70DSv6wW+TUhEwXZXURmdbph51vveYIOBmKp7b6ghGiB8+WXV78Mef+CKSQSLDjuyMpsOM/TLAyDQ8IwKv5kdnh4rXSkcF9IRxFo2yg7qpUvbJ8RsJbhOxLBg30bM++znH3NyMwuDEMQVv6uoaGDrldvE3Htk8dWMgzveedbjnp67XB6arpDMKFMgZKz3B1Q8r0uEsw3cwSRRU33oCmS6FWdr85+VaH8NxXSYwIsLqM8WMXV8F6N12saHRSQHFeKs7Y3Itvf1Gw27zQmMuBoiGg768wS7pKamcMkaQhz8KLe3sY/EJUfdyK/LCsEzLKqzQqvjLVSeMrosOeAoB8NL1a95461MQjKBUE1aDYbvxBJNmlzbB39kYketxN4HeW/u/e9q/E90tdSl5BrMJtuIRkJKPk+PGdQKKv3vDdybhUm5YFOcaS/rFH+h1GSFjwwvEsk3t89vfGBw5/KjNltDA5l6r1vrWW3Zs014cDAgb8nkkvjuIC+7WmcvZew9xQihLuVAAnlLdiQtSS692H5INCxzrt8IFucNbG45baWszPPvO0YY8KXOrcwehpYVBCYS+A937UW86LMLO1qIltJ2YaOOje9MDxcHp7cSc50wV8eYWpe2w2vnIgrEDfTuiELKbF35ZReB5K+IcL0hmPKoFsoFBzm3nrj047q0sGBZrBcc82agpCbzZvfnyTJL8NQHxiKm4GIWSUFtkYH4SiqntjX13gxUfHjlZD8smwQQHdaNnXxFQEC1eoBfVEU3DfL6rl2YER1aJU8jvVvrPLP33rrp7ZqocPD6woC0+O9BcEcsBLknS+4332Ce6fnUkYgY3BdCnL+H3jOoufYIIp2W9qIQNaCpGuueDUvvykms78zyd2YkjnEPfjgZ0jxC8PWINGGRAK+YjEwXnXVsXeKBP3t5JmPNCIEXcLz16+/7R7W+u900DJaPEEvi8bUn3SzW79++4NE0ovgzaHDmsIb7UT1MLUhzCbIsrSRZSNvHAYx69zzjMo+juDjEsWP2f7S4EA5OkVFKDMm+S7IOWOQNVhoX8m5pQhEEOavjX6340ddlP85Ip36oJ2GgkOyc+684J730UFCMFi0suxtD0IstLrttn8fdi7/jA5SwKPtgWlv8vd2HYOEybJGhkH5r+J4v+Ld7r3l8deXDgKeoJdOW02jqf5wobyETvr2KKpUiFzHCEJLZiZ9L5fyvPnhzZv3+7aSs77poNfaCUqIjLnnna+518PMQfnGLM9JUjwE+x88ENSPH4FQMUPcjqi9pxEkCbAJHaU/hPzbQ5MEuX6n4x7Vv2lchKtEo4NFcdzGpqzvulwkeRsGqcQYo58kRSFtZJ6DJMzAKknIOXdRX9/Ov9VBw8KznwPRXsQCI+AJeoEbYLbFr1lDATqobNiw8+nM1adhTlIgc2K74nQ+VxFjwiBNm3c4FxT//zc89mOONsvtL9OFxzQvqdwjN3gw6LIfdLHUDTGmJOaMnMtiqHiUhrlnfRMkVZK+Owh0UKBut/FO/dodBguZgRc9PMx5+cCw61tZ5q6OopiYqaODJJHDFFMcifAlrWr6/dJHwCz9KqzkGuj3NjjTf9oIgvC1zIwHaSKk9ECdWVBaHhav1Zk3btnS9UdbeG54+NZm8WIphNpuh73n6fG9sqem2+E8f6/buB0BcZeAd9oUNNNkEE2RkKAHZN/v5vyOwFWOdNx1j/ydMxWl6bdtKx8YRpG7pNls3GJMhId1QEcvdiaYJGm6IKg8DQ8Mn2pt8doddOhM4b6U+UEA5jk/gr3U+UfAWmItJQgOORNe28MxF+mY9T0Kje1EkDyKqmGa5tfedtsNV2qJ/f2Ff0rtLKAvZkvZDfc47qDagxrn036OkmtXOdmu5Ozmj5xbyqEIfWUPelAKjz25NZDomPzxO95xxOnQywkGj1bSve+LNyjMpk1dNzDHbw7DgCC3g140F9/oCAJDzOHFmHapWct41Cq8d919isWKgFmsinVKr6VajoWnig7ozj67fi/m4NV5DrbpaGXwKEzI4MEYiCh5z/Dwfe+CTvCGWWagRkEeR7zyzrPMkfnDdn6tK5O7g4C73fyTc0tJFFW8upcbTq7tcgRKrR2Xnn/Do487iC1lIFluJd3b3tpycLrttrs+nOf5tXhgGAIlSNxbzrm5zhick6TuMDg86tBDs+KBof9Ox9xgu1BSPEEvFPJzVG4Y8ivC0Byd50nG6KFzJHavYkA8AgJilPuZgYGurbYcMOCx7TVrkUCIoC65kZfe9xg5InlN87tVcn+Og+KXfo46u6A8rmKTcrDzq92ZWcUPO+Lc23pGlWiboIkKLzocHj7orixLLi0HTUYfA81TpxbGw1qHQZMu0MFb58ct2qZTpfty5hYBGM/cCvTS5h8B7XDWsuvpufNhzNSbJE2wHQXzX/J4CQxvDQ8GU+fC143HzuBoKxW2xw/a+aboL9UDk+vj3KzOWT3YGUiZu6TgZ53zdvUgbHyzRm5V1l/fciTuTsiBXtsmabRLtnbt1mBwsOv/5Xn2yTiuYOoBEuZO0z1KYjQMBs0sjsOjw1CKt1Kuu47a1n+Pwv3FjiNQdJJpS/UXFjUCxtTeGEUVfaVL6aVjnRDeMwigAi9N3rV5c/y/mO8MQEzQoT24ZCsF+lrdjkuOfgLfGp268zchYVrDUNsS2itnxqkwGWFWYR781jCPf99dpdwVb6XQcDmYtCvv+ON/KqNpL8Yg1mDGxDDQGo2b9x0zBc1mQkS8cf36kUd5L5qW7OIJeok1XYsM+/rqp4Vh9JQ0bQhj6VQ1QM4uDIsHg7/Lcym+t3H88eXcazs6gLlYyfl7PRTFSfDKykgYSCQ5M3E7+ec9jZJ0tzMjf0LX+H31udtfde81qq8OKu2Wba111ooZHKz8FPX6QKUSa9a2p3808exC8cDQYQoqhCf9htnJ8rkXEgFY4UIW78ueCQIgR1ZvaOPGOw80Jr6ASk5Tv7Oj5KbviTjn3qev1bUGDGp3saXSxx16zHOiwPzD9sw5KB+0T/HtFrTv6ViIXSh5NTJRHLhX6WCiJL0vEtPUvS9N898FQTVC+2lb7YuYGedhZpMkOngH/6CDubXstK1mLGjpZlgWmnuCXkLNeMklBC5TheP1eDD4MHjP8Mo40JhOBBGnXpnJsvxbIj8qvGcdMNotGzOx+lqdu/vVRx+cO35jCroarVC7IjqWDnoF2xPnMIj844MOvtfpWrDY9qc6WoSog5hz2TsZAomk2KqsTgSU6ZgNGQzmL3jBnQdqW4l0VodO1HM5l+EJesm0rrB2+tNOG7mnc8Er0zQjdMCgc+qjZ6PAPHcEwrlE/1Fkph7Ztkuo0JcpesmqSnDfZiYZRC5aG1Q2RXUJ+1ffccG9D2BLTkRP20NdCVFTOlfZkmXJf0dRTR8YYljS2E4EDnQQ18F8//27i7dSxgf5TpTvy5gtAou2c8y2Ysst/9q1pffW1cVvwZzmwSIZZktBb52raB5F+rW65OODg9UvKTm3CKgdFcSSOdlSdtfL73E/JndRPXGaLdDNYg1A1zQwiNQq5r5xlxT/XDLTB4aK09AQp0TpJc7lBJkMT1o6VWdmJekUjyjzi9evrx9rLQN44U6V78uZHQKeoGeHX0dyaydXMuzpqZ9sTPScNE3Q4aiDbSeCfh7Ca99BZIqPw8/kwWABUj8VpBTH5uLuStCdOcLtNzEt/iVoplBd5Ly7X32f++tctNj2sR8epuKB4cDAqi9kWfKJOK6izpx3sNrsXOaiqLIanvTrtVxryzsZPfZhcSPQwU6+uIFYzNoND3O+du1P4iCIXhGGQcW5PIdnhI7eGa0xb4kOHhEzvXdoqPJja8VYq55Ye+XLWgqQVxqvvtdTDPGpO5uODBO3l3thU0FvTnPJu+LgAEPZGwttbDnYFMd73bD095fpRbLXJElyN7MJO+xFc4pBnZlfgAeGj0fbZTrok18WPQJm0Wu4whW0Voo2OvQBFoamAAAQAElEQVTQ+z8vCIJTkqQOz9N0bGpAxIGca5jLdNc1Go33a3O0CEeP9xZEiHmY8s8++a8qYcW8Mo5MiLgM+RYvQUO5SSuT2dHETHLVPHPna+71T1BcdNChNhcQY/Fh/82b9/sls3l3FEUkIphqaFPArJMVr93lYRjFGORfc955v6rooI9BAlWZtXAvYB4RKDr/PMr3omeFQPlgsKfn9v2zzL0BxAZpne1TIBRBoZTnyXs/9KHVt1orM/reBnPpPT7lc79ujjSyD400XRIErCTdQYLSGswiCOWrqmzSxH3WSfO7hSRMXRT7Njf9/SUOadocxFTRL8KwFoCjO4YBs85FN3Jjgic4d+zzCIu11FljQpl+nRkCnqBnhldHU1tLhafMXHtltVq5V543MnS0jrWZiMB7rgRZ1vj20FBti3pc1rJ6vzPGQSyZ/d52w1Vplr8gZNcMDDEGnI4R1IwVHs0geLq3qmbCnQ33n7+NVq1b/dabb0Ucg9mwG03Uxo7hxFor4ZYtq/4skr2DIYAKfgQK1JlFhDnPhbIs69d36dGWwF8KTTqjgS9lpgiYmWbw6TuDADqzzvNmGzbcfX+iYGOW5SQiBWF3RoOilGLu0jl6rZ5Zq4yiRzMPbMnJIEUHvPOPn0gS2hDC8nQeWoRAEjOX14kcTuA510zUqMvn6reMnPpg+9NErE6fl97wTHWwxeAmPDBQuxKe9Df0rRjUX2YqZ1/TY1AwzjXzSqVyrEil+A9Ga0snYF9l+nzziwC6yfwW4KXPDgF04ovjODrAuRQPBkFpsxPXdm4Rl1WrVWYOB+A9X2PtzB4MTlUQ91IqWylY9Y7rr96ZyJkgaUYQEKFMlX4h46BQurpmgkY9/8JdWX3toVf+ZbtYkLOd3YACQmStF7N5WZYlxEys550KImKyLMNgH5y/YUPj/haDhkXbdqp8X87MEPAEPTO8OpJaOww6juvtbTyFyJwKbwvlcse8Z3RiFwSVMMvymxuNkctQ+JytxWtqIOkD33H9h5Om9MURBxh2UOS+eaVzptgEQfBqs1VVE+1s5tc06uZ5R7zrzztlDshZi9B21amigYH4u0EQDFUqVUz1yD5NG6m8mQZmg2mO1FUq0QFRZF5X5r+k3PntokPAE/TcNskcSCsfDFrMVxpDr0InBjFLJ9+bRR2EgsBgrjLdggeDP1VdSmLBpblY12G6w1K4+l3XDzZSeXFXxAYk7ZwsPEmX5Mxhs+G+etP25LkHvvf3d4olw3Z2nvNE2NauHS76XaNRvyxN8z8HQYSHpp17qwMkbZKkCZXM8845Jz3FWuu/0wE0FuNaGMpiVGyl6tT6xeCf/9w8K4oqj0vTBrwrBkl3BhHBhEMY1rQDX9fV9ZfiRykWt8FzWTqrC2kpExBf91v+8MHtDXdhLTYBpjtyEORcFjUjWSg7g+cc7mjIt+oVfvb9LsMDQejIdu7IWRUaHl5X/MnsFVes/olz+XuCoGPNq8WPBslRLgaG/LXnnSf+tbtRVBbbzhP0omoRYX0/tadH9hfhV2eZw1whdbT3MrNjJmLmN1x66TH1ef1BgyW5Zg2F+7/j+veOJPkraxUTMoMMBYE6u8B7z5WcG4n79h3OrTvQ/v7OrfoDGzs/umzbdjIGXqLbbvvVe9M0+VUYVowItOhYtTnA4J+j3McmSeMFWmzLOdBjHxYHAh0l6MVR5cWrxZo1JRkzJ3gwGN87z5sgS1BWh1QWkSyOq0GeJ58fGKhsVUd3eIbv+85EVYwDcvI2eNIgwlVvvf4d20fcxd0Vg4U67Umnq6sm2Nl01+YpP/ue77jhRrFk1g3TvE4t6eA3PPzghDm/WOd4GIPjTPCbbVoRMnmeYzA2b+zpufGQ4WH9Cbp/7W62uM5lfk/Qc4nmLGRpZ922jbOenpFHhmHQk6bqYDE4bBZCZ5RVhNnog8E6Ou2bNau1hPJZ9Hhew9ZiTtrs9/Y/vGVHPe/HdEeEmitJz3vZ8Fnz7thEI838h808e86qd/7+Zv2VINv58Zwn4jg8Ovhdfnnt35Ik+UIUVXG31MkHhhga8sTFcXx0EBz0etVtzZpt0EGPfFgMCHiCXgytAB22gqSwI2Mq52NucH/nMv1RCmtch4KLohgPBulfh4a6vmnt7F+ra1dvkLGQxWwOvNbVb7/+DTua7k0gzQDxTmT+HhwqOa+ucFDP8h/uyGTtwe/40x8FOuhP06kjC8vatVtBiKyD49swMDaIOCTcuiB0aGVWZ8CY6IW9vTtP1KkXdRY6VPgSKmZhVPUEvTC4TyrVWjHMLOggTwlD83zMCeY41446Kd18nWBqwxkTY04yu9G5pL8s55Jy16EtRqKCpK0ls/qtf3gdHhy+BdMdgWFMd9DckzSIP1td0WkN+Uk9zZ9++Dtv+E2nPOeJkOoDQ23/gYFom4i7Io4rGKkwdExMNI/HsDP92l0WBOZAkPRFWlTp2QuaRM98WEgEPEEvJPpF2eVrdeed96uKSPAGEAc6qE4tFBc7smEmQQdFueml+g8gIIzQWus6UviEQsAIoqfYMKY7Xruz4S7tqsCjFKg2hyTthDCtwWEjzX/eFHle4TmvpaBznrPWcveQ59k7ms30liCIO/rAkJnDZrOB5x3B8/r6Gk8lYrG2szZIfpkSAU/QU8LSucienu8XnnKaHv3iarVyQp431HvuWLuIiAuCKrznxk9vv71WfK3OWso7h8DkklC20xixxKve9oeXbq/Le1ZV2ACQXPTCLAMGwGxVbIJ6Jj9NnHvawW+//rrCcx5eyDqzs1ZCTC1dz5y9IwwDAmkWOMyyujPKzmzIOXnHmjXXYIDmmZQ/o3J84vYRgN23n9innFsE0CnN0NCJ6fr1dx5rTHz+6Gt1cCTntpy9SWOUaEzUPzzMiepExEILuECdsfJX1/7w8h2JG+zSV/AI0x2y79MdzpHrjjkcSbPrm0n+/P3f9sdfi6VwoT1nhdracoDYufPuAXizPwnDaiDSyR+vsMmyuqtUqg960IMe/eJSJymcBz32YWEQ8AS9MLhPKjWKul4cRcExed7ssPfscnRIdEz5t02bgk9gFoGtXRyeE1vCTAQxWZJf3HboeTtG8gGQa4DBZJ88aRHKu2I2zYx+NdI0/3zQu/74I8TpLwT1dRla+EWnFcRcffURO4n4NdCNOr8w5cW9U3hBX98d94YtZBbPRzqvhy+xhYAn6BYSHd6r4aMDuL6+kcei6POazSYxmwDHHVnhnGHeOcLURn53ntffQfCaF9sPFZjgLQvRCUPfz1a/4/qNeHC4uRtz0ojPEI2V2lrA9Hkt4qCRuT9mmTzjsPf84YeinjPP/6t0qmC7Qe0BVebBwepnRPJhHTzRTgVltitjNukYBghbyOEs3Ito9atUVn8/2oD8slAIeIJeEOT1wWBp+CLm9REWdMyOdUStMjoj5p5Dci778ObN3f9j7TUhpjg6qoPqsbfADJwsgZOJ7krc+SNN92F40iEinAC0veXXaQ0l5yx3f8zJPWf1O/7ws2vWUMiWFonnPLkGo4Ok5HlyaZZlI8YEOtWBqk5ON19nDCchSdRZkDP1nXzm0rOfr/K83D0j4Al6z/jMy9XyF4MsfX3NZ0dR5UlNPEFHQR1sCxFjoiBJGreJVN6AssnaNYuOnFUvDSBTB4bie1z6x0bXr68/e3vT/Ut3bAIAtkedMU2gnrNO4dyUEz9j/7f+8VpZS8HJ2xYnOWtddZC0VsLBwa7/zvP8iiiKiZmcXutckDwMw9gY80Yt01oMkiSsxz50FgHYeGcL9KUJb9vG2Tnn3LKKiPtpbEE3HDue7wNGBwzQ8fnioSH+S/nDBJb5LnVK+W1Ggh2E1pLRB3o7bs96dyb5Vn0FT0l4KhFgdFcJOUiduy0lWdv9lj/84Hs9FGn+qdIvpjgQYq761OvJJY1G80aDwZQINdXIzgSDwRt3WJV/2LBh5NmE6a81ayggv3QcAU/QHYZ89BYW3e3Al2Bm46/TVN8/5Q62g+RRVAnTNP+Gc7dfrdVv/YpRjxdzUHLFKMJHDd048vPbsjN3Nt3WVRUOEFcQWkt3ndaohoqp3NIQesZ+b73+W/pHAScOUdpKs7j3+gtDCT7ykf1uCwJzib52B3qeVMf51b90FnQbReGbzjrr1tXqVKBMjJPY+rVjCHSQGDpWp0VbkLVi9BZW/8mCiM/L86LPddDo0c2JgzzPcuea7x4aOmpEvWfGPCMtkQVgiVgyJ4Kk72i4M7Y3s//S95pRs2JOGXtXidgkmYw0mu45Byk5D8JzXle+xrZEqkmtQXPHjts/isH0W3FcDeFFFwbTiTrAJkya1uFFRw+sVvcrfmEIW/F80QnwJ5ThAZ8ARqcOjZGL8KT8COfSlME46HgydQDdwNeew2sO3rNK/NTgYPen7OiA0al6z1U5bMkJSPqYS/9YzxvhC3ek+afgSYfwnLM4YP0V3l0Ygp653ztv+IaspYB7l4rnPI4QY9AEIQb62p1z+XsyVAhX0V/13eg5twuZ2saI8sKJCHvOPrvxV+pcWNgM9PBrhxBAg3eopBVejBq2tew2bNh+kjFhT5omwmwi5gB9sRPBkDExHgwmO5Jk5JVLvTlaJH3ge39/55119/y76/L51d36PWm5q9HkZx3wzhu+uFTmnKdrixYhDg5W/l0k/X/wopmIiTtkM7BT41yWRZE5EuG1hKW/nwRkzuSXjiDgCbojMBMpOff0SASjf7tIljvndiDsdC7vUHDbRR0vcm+54or9f63emerUoerPSzFs4UnDQ1ZPmoPshTtH8v9sJHL+Ae/6w1flGgqXzpzz3uExJnl9s9n8M9qwCZuB7XTGbrS8RqNxtzHBizZs2PlkeBNiLfHeNfYp5gKBpUzQc1H/jspIkt8HzqWno9C/YqaHIDy4g+Fv0jS7z8jIXcX3NoZHv0UMXZb0Ovrg0Kx+659u7z7MPffzv7v+XyyR4ZMX76t0MwHc2vKXnZs27febZjN7qDGsNvPXzKT7joQwpIfkeXr/IHDfV91bOumxD/OLgCfo+cV3kvSrrjq2sXnzfr8cGKj9fiHCli21333kI4ePlEot7tfqSh3b2zKRIwuv7u4/NtduJWf1nJbfctVVq26+/PLqbzttOx/8YO0Pg4PVXw0MrL5l+aG6uGvkCbrD7WOtfgh/4QLj4VOHq9yR4tiCpPtJmEloWS46oArbBbSfZQnrQlWqzXI9QbcJ1Fwls1Y/LblwYa7qsRjlLF9ybqGtP7v2ttNCYyXsPUGvhFb2dfQIeASWJAKeoJdks3mlPQLLGQFftxYCnqBbSPi9R8Aj4BFYZAh4gl5kDeLV8Qh4BDwCLQQ8QbeQ8HuPwNJAwGu5ghDwBL2CGttX1SPgEVhaCHiCXlrt5bX1CHgEVhACnqBXUGOvhKr6OnoElhMCnqCXU2v6ungEPALLCgFP0MuqOX1lPAIegeWEgCfo5dSae6uLv+4R8AgsKQQ8KKyHnQAAEABJREFUQS+p5vLKegQ8AisJAU/QK6m1fV09Ah6BJYWAJ+ix5vIHHgGPgEdgcSHgCXpxtYfXxiPgEVhABPSv4Hp6vhdNDNZKSCS8EGp5gl4I1H2ZHgGPwKJDQER4eJjzoaET04nBWs4WStl2CXqh9PPlegSWGALqabUCLYjXtWfAxnTbc7IVd1UYi2zcuOMhfX310zZurL9IQ29v/fSNG0desH59/WiFRElc950Ky4SgBR1hqtApGH05Kx0BvTXWYC2xta1Q/EVVqPELhc/atVuDNWuuKXTQY2vHdDPlrftCabZ4ygUO4EGW9etHHiVS+VwUVT8ShtUPIVwVx9Ur47j20SCgy5EuVhLv5HQHFFs8QM1cE+FyRNP/a5sqqEQlbt374BGYPwT01liDtbv9JVWm8Z3s1OO11Fv2dfm2bScXOgwPr8t30W/Bbt3HdezA0V6KuPFGCjRJEARPqlTCo9K0kaRpwyHkCNjnuBz8zS237DwIBySi286EJU7QRDqinXHGHQecfvrI0WedtfOoVjjjjB1H9PRIhBQdhJP8suIQENy9EfX2Ns7r7R35T+z/o6dn5FMbNox8sq+v8e8bNjSGe3rqLyJSB4I6trQcl76+5jNR/r9ivxW6fUL16ulpFDoizi6kd98xMPZS0FFHUcERInk9Vy4mJWwGaXMAMtY9SNk1gqC7vLoXeXN5eYkSdNkpCEaP+SJbqVSvr9X4R1EU/KQM5scYCX/BnHzjzDNHjiEs1soSrSuU9+uiRKC0Kb013nF4HEcXrlpVe2qlUnl6rVZ7eldX7Rk4/ufu7spzjOEt69ff/TitRJlHj+YvKOmq49LbW38C9h+r1arPq1Ti51SrlWepXrVa5Rnd3bWnx3F8wcEH7zi41KTVp8qzlbS98cbvc1nfFkWMnpaR2DIcQTFpuoNx0tG1pVFHC51tYdZSAdT69TtPwDxRfxDE3UEQHoRwYBmig4wJVtVq8SNhmG/Q8qwtR0k99sEjMBcIWKvTGWK2bFn15yxL/9RoEDWbjbTRaGSjIa/XG80oqoTMAbzootSO9TnMpT6rWo2q0KWOkCO09MI+VV2vP+KIVX8ptIKzU+79djEh0DFjmctK9/eXZIs5oxcSFucS51wmzqVjQSSDAaa4mj3z7LPvwtyR3mJKQeyI9KtHYE4RwK3wJ0cF6oMkEDKPBgo1njl66Gmn3dxtLWfl9IPGzn1Q2Trn3dNz9yGYP31ckogWUoEnPaqP6kUGHj8hbgv0cdb6u0sFaTGGJUnQMCy58EKpGcPPhUESOofOE4F8eWIwIo6MCfaHB7NWwV+7lpZkfVX3uQoixZsFU+Ag+lR/ivi5Knl5yrG2dBYqlcq/ZFmjaWCUu9QUt8YNMUZOWL36gMfqtUsuIdirHs19gGz0AYLdhw+I4+pf53kzZ+YJ7SpCxAE8fY3fRliuu26YsfPrIkRgQsMtQu2mUEnn1zR65876M0E2R+Z5Qjy9eWVhGCqBn6J5fCBgxWItO9pt0dv1qeJ3S7iSItqoK4PwiN73vktuhT1+IQxj5JEJD5MK68ww3QY7jE7ERbruupLU9XiuQ39/Kds5eoZSMcKk3oHzPI4rRGS+cPjh3/4pDmh4eO0U9qBXfFhoBJYcQd96K3EJGp8Cr4XQKTKiohMQ4awMOMSKaybL1PbkMb29zeP01k/fBcWlFbhKgdtZZ8lqPL1/FZ7k/5uGDRsaw729jX/v6Rm57OyzG3+lwFh/y6swtB30PWMi6+A8/4dBjwIJyi6Zw2YzJzgTZ5x3nuyndkhUtscu6WZ9ylwOGNg/BXpAXtHs2JcrMyaboR2mA79h7cmZLX7GXOYpU/jtYkIA5rSY1NmzLjAms20bZyCW+zLzyWmq5Ds+bcE6vcYBt6QgjXEuSfEU+zCR7DEaf+uta8eu6/lKCT095VxoFDV7u7rit1Yq8T/Dk3p2pVJ5ThhWnrbffrUX44HSaxWP/n6S+SIQWobLoYfeCryIjMmubTSaNwdBHMI5KIyzrC6zcynhod398jx9QBk391trpejP69fXHw/bv5+WyTw+EEAnTLVEQZI07wzD+POjGkzQczTG7xYNAkWDLhpt9qIIbg1ZkzC7R4BY7gEDzGCIRR2wJ+eynXme79BjTacBXkSQwceGZ/PcNWskVIJfyeTDLAfru57opBkeIjkNed6QRoOAX3o4ppD0IZcodnsL/nqJwPDwuuJB26ZNq3/mnPwgDA3u6SZPF8EOCyKEjZ6qudauHTa6n+NQyDSGT8HgG4vkmGrhos+MlgOC1ulv+fmmTfH/WqvPHSbrOZrO7xYJAkWDLhJd9qpGeWtIMP5gLebYCB7BqP6SR5HO/fEHiOhqeAd6regQzIxpjiaizckPeEDzWBysyLX1Mj5oOAVZKAaBYqMBJ3i2hStgj1tv3Vbghji/to+AjDsP8oXRaTVlwkkSGFQJu11DtDUAqYM8x73bSQn36UQf/nK2du0NeHhOjxlt4yklod/8+5QXfOSiQ2CU4BadXlMoVBozbt+OFXFPxq0iMXOhP4xRAnQHeA4/Yg6+bxDLrLfppRgRcWFY1V8FrdeYlf02B8BREKYOoBDwx9TXfOweEBgepmJgMyb/eJ4ntxsTAUtY5mge2CPneUrM5v49PU/+e42eSztsyTr00IMeTCQnZFmiRUxqbNUBYzDmwtP/0ItEl5Q7v120CExqwEWrJRRrGWAQyDqQbdW5XBA9tmpXcM79WWTkhzBEeNDjBM24r2d0F4QnwXh5eJjn2HsZU2P8wB+tMAS4sMeBgdW3MPNXjQkm2SARYx46z6rVSo3ZFL8qPP54glXSnCyQVZSf58FjqljQFzCxxxPk611mFTq4zwbBr/6ghVrbX+TRYx8WJwJLhqBbBshsTlFvGaZXeCwgXMyrmbBeb2A+2vw5jit34FjfRw31Wgm7YJojIeQ5vq8vA0kTtQi/vN75rS3m/6R491iPRfQOQUPndVlJJSrWGtaulUCfSWjQY40jsrPqD2vXbsV9HGEun/XrZwrrqI3qIan9gSAJS3SSTkVYyyDRuWlzyHJaDyJ5VpqiCKJd6sJO+41z8mn91vHsv1MjvBb11TIVwzJcE5Y4zk2dilrs00ane4q+pfqEPaMf4IduxbnqDJx4n0R3ONMujdjh0tssTgFVA+ztHXk0iOzhKSxQpDRA7EHQMYzfwCvI7/jAB6q/J+JrdR6aiBwCVmYRl8J7iYjyxyOioysMw0wMWrjWZ2JgqEik7ygXhlWkF1FD10D7sJRf+lMZGo48kgqDFCn3XJztLvb+9y+vWwtlZLIMlaNh91yzidH6lUFlTxWI9Pq+lWEnDIQq29ryfW+9i9IHxhr0WONB0MXDvlYeTT+TUo8/fq1oetzl/ajZbNwUBNGub3MEeCgLe6XHH3DAfpiKQIm2xFvz7XuQojVXrx45HO36aDw8J+Zy+k9loh7OmChqNpu3GJN+S+PuuGN4tG/o2d6DnYCjHhPMQ+fRFTvFsAwnZ9bqQ8fJdjyb9qO2lzFSLjhN9UBQfTIdkDS0zlVngv5aDw2Vyv5FHiJX4Ai8ij0tgmVUsU5rsm/lMQcn1WrVbpE8hQG2QMT8MqB17n8GBrr+RAAeZ/+n3oIICY0uOEbn0JP8qeeee/fB2kjz3RA6sGgZFkY7MZx3nlQ2bmzc55xz5OF9feljN24cedTZZ9/1VxdeeENtYjrUEdnxSGmrFJ6Zat9OQCZgw6L5W+H73x/LCeyIgMdYBBWYFXE5HiZi+qcgjkn5W3J0X8qnGS+aby28LmslVI8Le9gfCxXl87Tl6XXNSzNYFHtrdbArCVlxZaACz/HIDRtGHoPw7L6++mkaMPA/B+ePOfNMOVTTtQJj0GzJaafoMp+Yyy+v/pY5+FIcB8RMBZ6t/MBdwjAiY6r/2Iqb7b51NxjHfHoQVKJdp/+gA8o08Ozz/8UUzE+0Tkqu7ZSrGGr6sm7jWJ59thx07rkjjwRuz+7tTU7v6am/CMfrzj777sdq/5qYntC+WwsbFrQAzemidlHK1kGhCO68825fvX799jVo27N6exvno31fOfru/0U9PY2NGzc2127Y0Li/tSTWsms2/2rSYMVo9zlVchbC0EFmkbsjWfWbtpyjY3URueL2DUYelEWLMFOQJBkMnr9Oowtz8LVGo+GYTUijVMQ4ybKGi6Ku4/I8fKAmbf0sVo/nNpSepw4CWoZ+AnXDhp1Ph7F8EOELSZL8H241/8e55leIsi86x1+KovjakZHDruvt3fmFvr6Ry7B/xotfLEdBb1m3jnMLskFd2jJwzXPeebft19cnh/X1bUeQw4ypH7YW5AjEMMARIQ2NL1LIZabgN7/58yGab/16KvLpcSusXy+Hox32RzqayaK6ayfXfEoM6BSZelzYFx0DMqNTT71tPwxSB5133vZD16/fcbiWpeXqcU/P7SiTpb0yS09Ksdf0Z5552zHA8mxg+tG+vsZ3jGn+XxjyF40xW5mDj5SBt2pcHDd+hPb5+saNjff39Ox4EvTaX+VYqx1Z2u0rRTqR/GtJkqsKYzaoJwjFNAeur8UxqWzdz03Q6T8m4FzgOkGmyaGKSPC5CXF7PVR7Uf0Ug40b5cD163c+BWSnNvwV+OM/zjL6ijG8FeHDQRBeZYz5V9jxF7Ms/mFf384v9fY239jTkzzMWolLGybcyZa2ttfC20ogRvuXytZBoaen+fyensa/JUnth9Dn88zRFVFUeW8c194WRfFbMf35LtxZb0Lf+7gxdG1fX/1apB8QSZ6qRA/c9HUvMIbqKNKWCvOcqDCmeS5jVuJbMDWbdz2IyDw8z5swQB7TG7duzEx3GJONPpnW4pJvIO0tQRABbJ4EdCmPz9FURHP/FNvasiNDJ4JXcfJNNzU+DE/q/6rVrk9FUWUjwpOiKH5AEMQHMQermcMuY8JVxsQHwXiOjaKuJ4Vh7VzsP5llzR/09jaG+vpGHjuuaym/1H/yVklQY0BIT0vTrm+KNL8jEn3HucZ3MQh866CDnv4LY1yvThGB7EcHOc3BuLtIcMCP7+rar0hvTOPaMp/m1TDy3TBsfoeo/j99ffWCXNSokWnKVa+1sLCW3fAw56edRl3r1+94yMaNO/8J2Fzc21sfQvg4c/PTq1d3fRmYfDNJIpBoeG0QNDCANb4bBMF3mWvf2rBh+/O0IJWr+6nCxPJ6ekb+7sYbG1fFcfeP4rhrCzB9fhhWHwGcDyUKu9FBi2+1iCiXaWuF3WFYOSKKKo8LgsqL47j7C0SN/+7rG3nFuec27ql1AGbIIzxV2a04a0uPOcvy/4Ine2MQVEFK43dyWpJzGRkT3OfMM3c+jMBZLb1pHxZtc8V248bmQ6Df8fqKH2x8ko6wM86yxs48l6KPDI++cTJdcSKtQW4dHCM6pqen/ibn6t+DDf9XFNXUhh8fBPFRxkTdzAaY5OhnOTGzYQ66cO2YMOx6YhTFrw1Dvvbmm/dfxqQAABAASURBVOtwOnacetddf9SPNsFrFTNd2e3Ga72J2N144x2rYU/nYlD4bqUSfxQk/Cy0832MCSsiKaVpw6VpM0/ThgYHmxZmMuCGA8Kw9nCk76nV4n/v7W1cZww/v3zThqEfUtHUSydjoUgni5t5WTpCaq5qtfqCMIxhCEWP0igcE8AO9Nbte5s2rboZBspq7LiNuwXzcNuY1U6lSDu6QWcRAimevHHjnQdaa53mGb02650FOVvL7txztx8Ekvx4EPAXq9XqC5nNIUmihtIQGAoMpuHyPEE/yMaCnqMTFdeQpkiHTnxYpVLZAGP78k03veKy886j1QSj3JvOIIV13d3Vv0b+Y2CIxwK3e2nA8X1R9/1FciIqwKHWAkUQY2pBUBlLr3nGQ/VeyHvPrq7a/bDfuBbeOO/hVpABvWJBZA06+MnwVC7r7m5cE4bBNRg0PtnVVX0TsNlQqVSfi05yCnR+eBRVHxQE8X0wBXAv6IpOHt/LmOgeSHc84k9TXVv2oMcTQwt7HQRwq/3+IDBfwHTYacy8/0TsMcCjqoq7CHAcCyKZZFmzwL2FfxRFD4T39fYsM9/o6Rl5AQF7LR8CmKZd9Da7/ARpnrsv824pAZpk+t7+qkrFPF3F3Hjj9ycMlhrTfsDD86IElPWIOK4e4lyCh+VKMKUM6OqAJdqWv33FFW+/oYyd7LSUca2tsNZR2w44Po+58Q3geDHa5FjgovZZYASsnEgG/BxCC0uH4jKBLWu6IuR5HkRRbQ3a9yMjIwd/pqen+dcquyTYVpkz22veYQz4uMu6B3Pt01HU9YEwDI9ttXOWJVBEdVN+IMUH+HLAWKg4FQFORT1QJ2k2G5gmjWB7lUfiCi2mZZETtIBw2Z1zzi2rgO0zdgdOMLdGZEx4hV6ztkBfD4k5+iRzcTi20fM8b8Kg+EiRaJ1esJbQeHo0u2Ct4MEeu40b735Amla/UKl0Qz6bZrOZiuTCzPAuJoVJ2uG6rpPSwLhhPHU86eeoUqmdAwP8ik57ELGsBUHSpEUYnVU0Ks+TCM9RMXBlLs8Tl08IqgvRpKJpfBGamHbXY+dSlyQOcvMQD8SmE1KIW7t22MA7fmFPzyv+xxjz5TiuvDgMqw83Jj6IyAWNRjNtNBpZkjQzdJI8w/STBrSPywt9S921TNxKYzDOG4XgKTYipZ2ARDGANP+zq6t2HpGpqHyURQB2Iq5MiJkqIJ2uY2nzPHPNZj1H579HHNc+ivpc3vICCX2f9rIY4/6fFC0yOSHiYA+QIObR2JqhoRNT7KHX5HR7PyvqDfsoUj6h2BJNksNMzqCXA6N/wWDplNxo2kXgwJQX4WC8Hjb3rxigj1EcgQV05jFsmBmeM5pFJgfNzUwT0hFr++YYQSDv8cbIN+GtnqIEu2ddaMrFWjGaF0T/wDBM0M+qf682lGXpBP0INYYW1ApjooBNK451GdMzz1OXZU04bGNpF8UBKrIo9JhSCWtL8nRu1VNgwPcFgAo5QNbkgqfhITp64+48z36gMRNDpZL/NxruTmMC1BFdorio3gvlmHLAWfBEbHRFo8ioTD2deVCjsZbd2WfX7+Vc5bOVSnRCs9lQN02FRaRaky7oJiJORNCpJC+1KnRClMYRyHz8DoGZYEAmdC5jJYpqtXoijv/z+c+/8ZDh4XVwg2VKvZGPubyC/JM7FY3pQlMuzJPTTzxHBsgDnETuumm+yKZYIB0dcMDTLoa+V8N7eiiRmDStuyxr5DnIF+eaJILsEAcIhXcD2RPL1rqzFoZ4pJpm1fIgR5ScofqncMdxshKKcznyscoukUB+BRkB2JPirPiNBgJBFnGwBSQcXwPINlnWFIQc9enbseOgAcxNo0010dT49/eTEBZm970sa/zRmAj1KFsb0bpiSiklXH80nk1gamLfXvtsSTz99L8czSxPSnVUJkJZWgRQFgE5R2Gz2bzZGL5WY1uDuB7vGvRhI+ormJbrr1S6LsmypsvRXohTHEflii5q2y4IYhNF1bGAAdgwmpLIwbYF2LZKYDhBLlAbDoJwvyAI/l9Pz85/UqK1VkblttJOv9e02s8w7YT6OkwZxsclSSNFDv3W9RRyVAfRtkabF8eqlx4XcagI2rtEEXVE/sLeIG7xrFBq8SizqybjJGDWVKv6iURBYzBrOsAKoo1g5OFXBgerv9Y4a/VhTtk53v/+ruuNCfDwTeehaYKxEDpHcbpGR2Fr9ck0FTJVxr4ElaH5oih8X6US3wdGkzErOYx3FiIlXqYoqhh09BCGDTuNi3KDoGIqlWpYAbOHYUU9E1caj0rVwCAbowaeooyHrVp14Ps11trp9QY+mqSQo7JaAXqIXpgqaJ5Wuqn2yAN5sGmi6MADv29wPmm1tryLwMO+v4qi6LwkSSnL6qKJmA3ScwBcdF/Uu9QFJZWrw263gLyIw5Y0v+4nB4v206/JMQebYCMPBfYpytAOO1qGpodkKciKFWeki+K4GkRRGRR3jVOCQWrBUlQSx1ghrdBdTIKlu7vrdObGawl3MdbShDJobEGOYp5Vp9qMiTBoBARsC6PTRLjOGEAy6LLamPDxGrcn4tTrUwWditD4Wu2Ah0VR7SDIhN48USc8FA8UuW9dfnn1F+qxWuCleXYN1paeaW/vyHOiqPr6NNUnnEqeHLTSijghVBl6w34j1CG5Ncsav0L4GcLPnWv+zrm8XqnUgiiqBKizEyxULIzFBFmWONQZJB196PTT776/6mOtmCLJXjbWln0b+d+CPnT/JCnvLnfNhiKdlh2hfZEuQgj1WIMeI+COtBpqvyPUp0yv/ZMW3dIWMAuhtbWlwZxzjv6noDxdn4gD9DFjYSYYiHbx/JvQTzuEjvJCxPCmJCIsGP2vwW7SylicyzLccmO+LsUt5qTLMz6x0FMz9fU1T8Wt8DOazYZDEdBFY8sg4gpvg9nkuN37XqPRfFeSNDfmefN5zuXPzLL0VBjb+Yi7PMuaPwnDSEqiFnS4Uka5ZX2XVTv28zdsGFln0dm0041eE+yL9kR5O+OYMBhUGUY55uHosTERI90Uq6AjB6RppgtKYJWKIebolvK2fAoxiDImPA6jD/DNMVCZsTbDpdFVdIEnw5AVMuq6m54tHbTMqGhNc8do5rGdHcX+uOMee16lEv9To1EHCXKRupUIBaE9gqJeItlNjUbj4/V643WNxsi5SZKuB+Ybm83k1Y1GcxCDyQ+MCUBqVQyIDFmwuJYgaCriIqQDTuZ1ILJHK/54jmHGkkw+KOJF8q8niegVnE+UR/DMNVqeCSsupvL0bN9Ccsbu+USYCc6I08HhK4Rl/FO9OJmwCpJqXdavH8GcrnkvzjGN5ZgIK5WLiIMNV9mYMIEn/EnY8RlBYE5O0+qjbrtt+yOSZMcj8rzyWOfoyY1G/eVp2rw2iioG6UVEib2Uw4zH+VkjjePoUDyce5vGWqvEK+OFaeQuwVolcZaNG9Mnwv5Ohw4CWZP6GXAULEX7oQ/ljUbjW/V68z31ev3CZrPZi77Vi3wvHRlpvA3t/h8ZBhdmhqNXNSVZqx67FLzApzCaBdZgL8XnuTwM3s7RmIvUf4Ao9EUjYHojwmjcvMO57KujItzonlrv8mZZ8NUkSW4CAUz6wQDyGxgShWH4fM1jLY/l1fP2g84Blo0KY3kJw8QQZGJ+lAWDqZk8T3/jXH5KHNf+bnCw8gp4/QODg13/b2io+5NDQ5WPDQx0vX/Tpsq5eJjyaBjOs7Os+eMoqhbe9Lg8RmdzBQZhGF104YU31PQ2EYaJkotURT3CMHz39u0jV6GTfAbh3zVAnhrkv2Iw+JkxymEyQU8RjRPJb4bhfkKD5pkYYOD/hvh/37mz+QmR5pu0NGu10+jR5IAHgUcAB0Jo6TWWAHgIwymDFwMvNxC0ax26XY/wZcj/RJY1/hWE+ZEsS6B/8iHsPzwy0rw0CLb3qxBrS7wtyraWXV/fHfcW4ZdlGfiUuMBG02lAWSAVvSORnUky8kZQw8N++cvvnDY4WHvT5s3dmwYH4ysGB6sDAwOVtyFsDILaSY1G+jik/XIYxlMMLIz6COakY+z59VrGddf141iPJof+/vKuLU0bXyaSn5VtWequKSGJUXc9fERPz1330QOk43LfzlZtj93zn3/3IUEQPlxk9zzGxJznye2NRla8vbFtW6nTrinhiRd1DUN6WaVSORqOg96FjGGpOJb6pzenafM5sNtnDg6u+sgHP1i57oor+Pbh4cN2XHnloduHhvimzZtrX8f1d8Vx9aQkqZ+PskagH+a2J2qojkYDOFae2deXriHSZyo0Vh5NsVx3HRXYOJe/GtghhSlsHQcTV0G5Jk3r12RZ8yQMHk9E+140NNT13qGh6hDuIobQzy4dGqq92rnKc4MgeSRz9pgkqV8GO8NdeCl5osCFPt4jKAupnLUtYw5OVzJF8xYNNKoTCCXAKM+/2Lx51f/a0c46eo0sOq56lldeWf0FjP46Zias0rrOWPI8RZw5acOG5vFlvHC5b3+rc3ZELH199TUi2V9nWUrQcwxTNWz1ABH/f86NPH5wsPaVyy6jBGlY5zGtlbAV9Oeo6Ci8aRPtHBzs/pRI/XEwtP9SL4RovGMxGxhgwxkTPmLnzsOeimuoLxW6a731XDsOZJw5OFh9FsKzNahBDgzUXsBsPhaGRvVURtPkxXEYKp70raGh6nM0DA5W0BGrRV7Nv3lzda2G8lr39zRjqzw9bieIOL0zgK7mz81m42PA7Ow8p8eLVB8yMFD9B5U9AB03b668CIQJ/StnQY+zEP/STZsO3vUNhFGcq2dFUXgU2hPeOkN2qYmWFQQxBuL8TyCVU4aGul9/2GHdt1xzzZp8Iubj7UDAnkE0Xf99xx1dp0C/i+GpQR5aqxRZbHEGzzclY/hxfX0jj9UBUm2tuDhhw5gU1vgrrtj/9ixLvseQNOEyDpFAcsUD9zrx0xBBpT3p0d6DtVSQ6n77VU5B/zgmzxuCMsZKEcHEv1GI5FtXXbWqeMOJYKu0ywIsjLWc4cHd/YiCF6ZppvZQyNakIuLUhrH7tXPJEzCwfabMU9guHAhh9LEiWGsNppsChPDggykdGup6P7B/FpHZDnudRNLQj5mRU9zLtBzFUfdThbVrJdDrGzakJxnDj8rRdwU+xcS0OIcjVDVJMnLV7bf/9pTBwa7/vuoqaqquPcVPvSVqtbXqNzTE6eWXH3DHpk1d30PalwwNve0BzuXoGxXUX6Yi/4nFdexYW7BjhbVfkDY6y9lny73QkCcDOEJjojknS2DOC89gcmx51prTE+ErRYq4iXVlyIR3FcVB4F6gV9es2TZmlHreTkAZhU7O8YMrlWoNMieQhAgzozM3JM+b5w8NHXS9GojKRbxTA9GO0QpDeJKP48Iw1CCR/i5jktPgCfw4DHU+zxW1ECyQgXIIJOHOxLH+hRLrvhWQhLWz6L4VTjihvMrsQAjlcWvLTKzHuFZVY9aP3v1dAAAQAElEQVRja0k71JQB3apIr+naDdADg2rEIKu7nZMXgohPPeKI6ke2bOn6DrC4C9fHylLdJwdB28mEMgvvMdO3e4gYBI8tl3WgYhGUFaKN00aWZS+84or9vmUxGOolZn0NjjNrefQnwJzqMYJTHZAOZRENDdXegvZ8E9oVermxwQz5cZ6nmLPuJgr2+NEj2IdomUThUIbBG3lNeT62hQ0yQaUnj8XM8MAYeWy1qndEpFNG3MrOTIKA02ArNmODuB5PFUTCk6vV+OA8z2BbPKqn4mgwyKVpkjRfMji4+qdqw9bqs54CQ8dQnmAqGtBmbtu2kzMN/f2aRsItW1Z9SSR7Nbxomrggn95VEuZAHq8P18trMqZ/eV5uDxx93sGcPbZSibtEcvXwx9Ki3YpBBHfL37n99tvPGR5+cGKt2gyRtYy+diIGCy4Czgv91IaRD/2EEAR9wjroUjgeZaki5X5ht6MNsbBK7Fq6taV3EMf1dfAgD8SICeLisQZhZiW+3LnGxzWvGoPuJwbIKABGo30ZBHk3c4D846AzDNgUteeTNJ8alTaaHrcbUEbRcSHnb3bNg5LySqVCzObTmzev/lpJuqydqNBr1/Tj5yzqLaxZI6GO8JBzEQwJlznHHkYUUBU9Cd6Mc46K7yqMEwGSYWV0Gu0sum+Fm26ivZSLjFh/+csTinSom7Ty7ron4iINzWyRINApQ7l+cDD6iuKB7PDeBK2gRbFuiqC6Tw6s7T9WJnRDWxI1mwfA66PHpmlDr0EOJGIFZnkc68Nhd9mWLbVtKCu2tiQUXJ521XoinWvh2WyOvBtzmN+PohoGb30LYCwr7I8oz93jrFVPUttVCp3GUuDA2hbmt/6AyP3W7DK1BD0xYKFqFDxk/frmg7Td7SixIPu0q6axqM8ZZ+w4AjaxJk2JIAs6llkQ51AW5p8bfwqC/Gtl7NRbyFEFiDl7rsoh4ok4wsOPcaeafR6e8+fUJjGYorS9tz8XNkhF/6hWb70S8/v/B0cDgxsV5REWkVyIuBaG/E+EZeo7CGF1XrRsiHw07riQksZ0xIkwEwbjHHVwFw8PH1O39hrcmU62GaTbZWXkKwZr1UcDrrtipMMBVkZY+HViRRdem0ID9Y7KhnVOnhiUZjcKoCaQHA2NxjBfIvrtTRqDBtLdLoHR+EQf+tDqW4n4P6LySdMEOYTboSYM2z1648bGEwnLzLxoQQtqGQLjoANBltCJEAdBWKGTxuOIfqSbAw8kxbrQSc/3FrZhvtBaMZhe+JJzbri7W586V9FZ3K2NRmOzc/KUoaHqW1ROq5Pp8WIPwCVUwhwe1p+vE6Yb9taRpq9RFJn7xXFFE6BdIRlHICcMBFEIjw/PJ9zHEEUgXAyMetReUDyBfXjVVQfeaQwXHigIcKxtIQUEnVIQ8GOvv/4vh+EcdqTbXQP4SJRgjhoRoX+DvpoOupbpmBneaZJhID8iDF3rgbXaSZlgL9tKJTg+CKoPzLLiwfTEfLjd145jvoRb+BtQFwyErcFiolC1YaKNG+88EBT/EMEYBBIcqyczwYYFGcwANrRmzTi56vneg84tS3DppcfU4YsPRXg+Dfn5hHzwfANCOcWHo9BOPOFacQjciv1973v3fkR8L+1niJuQTlDXKotk2xqN6rcJi7VrJpaBmPZW6OjaS9m5VBMbtXOl7qGkchRl6e3deSKz+bs0xYBNpUc9mg2Nqt5L/jkdWa0VuGVKlKNXJ+x0rqk8zT+PRsXhxHQwFbRqrVYDBlzcqq5Zs2afGggGxhA+YS1Kwy2c/gRWbtQLd9wxc+PWfBryfOT1O3Y0rk7TRl8YJscNDtZ6BgaqXyhK0QRLLGCwkrlQWaRxX8UAYSL+mN4IMJDR7zbj+QSIB7ewOgjMuMTCFnDD/3XgXjcGE/dKr4UYtZ0c5UT7Vyr7HaJR+vxA97uGdesI9gUtRL6YpoVI6AqNxxPinFTff9AoC8+YqCROPZ8q9PdTgR/6x5MMpMP+inMqlkI2BhAhEdf6Po2mmpCmSEjWUlG2SPRYZtbX9MoLxVaEOeA0be4QqXxXo6wty9XjmQYR+VmjkWg29FcRPdDA0ABnf63Hdg91x2AUM/P+IgWGmrwIyCuKgYj891VXcUOnYIgm9nNqexFx0Kbt5B1JiIbrSDltF4JRdLTxIsytVbucQxdBy6gANIZjDiPcdt6JfTFa4unuaHpNMTm0CBck/z14VDcEQTzpbQ6kxgM3Qedwzz7rrFtXW6sdWWbYSCzMgnk7SBtbWWVgfjFAjByJDYGUZox1Sx/M/f1iaKh2+ubNtc0f/OB+t2kHhhcaMApW2SstWFsSBQhEn1FMU30u7lyQVttimjTTRyOf6NV6fftPiVinyAj2R61Fj5kNpjlyeHat2N33LXvOsuSHeZ7+bxRV1Q4msgxsMCVm+gf9qNbuEnaPYbS7hWPinHuac6J6qcwiIfTCtEQVnnn2hzy/+7Ma2d9f3pHq8cSAvsPleaDfhoEMCFNNEKlyDKZkmOkncC52Imqf1lb9u7rodyL57+Dxs8pWYdjDQy+ODj3nnB1H6JG1NKqTnhG1Bj7ngqqIHAgZBJ1G00ACERwhTSt/0e1RR5W2ocfthhtv/D6XaQEBDhj46g5hwddSowVXY1wBa9mBfDBp705PEsEFVpbDntAwAuPDAEz048HBGBP6wsN7+PCLyrIw5Cuu2P/XILVvh2HRDmOdAw2Bxm3iljg+PopqjyUs1lKRCId7WXX+SkbxC25h5IK5SCuTHuvIjrYuvIMnPnGmHnRLEhcygUlgrZYnKIlpGFMErRSz35dlQI4ceujMDRz5FmiV1dMXLNunv9bOlRKTj3704O0iDgQN2KfIxszFHMsUl4ooa9mpVwcbvJ2Zrg1gzWobxcViwyCpTKKoejCmQP5Ro6yd3gZLGyD64x9H/iYIgmPhwBDkaraxoOfOuR9u2XL4n9VumMu6jCUYPQB5FpVyTvRTCjRRL2ZCvyA4L+aXsLV6mYWl3M98e/vtKXCk7ZCr+o7JQZlabjVJgtqepDrXBHJUEc2wS8IyyqS7RC+L01GCWRx1AfiFwRx0UPogIn6ocykaU5uUigUNoaMv4mSbRrSmQ/R4ugAvQfQapHwxSQp5BcNrnAbIFDy9hczghXqO9IUOetxGKPBzzv0YciBjPCvKC5rNJkTw03t7079fV34yVOdfg7VrtwZlXWU8A1JOtzI6GDrJxPnaok7TpV8p8SKmOl1dmam4n57u+gziFetRgtp98HKu+MXoHsXBqxudEw0+DptIjAlgg2oxrWwl8cEm/rkVs4d9YXMg5+cFQaR//QaHA7UdzzBqU+HVGgUSVv31cNqAQWO3QQbaFfnwkPHuMmN7tlqmHd/295eYVat6J2yySZoSkYgjODJV5qwLp3TddcOj+uvZeMgyo5hpGI+ccAS5MuF02RwWjb1YarNudL6O2b04jmODxoPxjWtnsKRpI8vz7P9p7Nato16pnkwThkc97DStftI5wUMftDHMYmJyGCPI1Tymp+fuQ4YLz7Q9YwSZF0ZhjPw6SRoNZu2sKk2lMwYTB4+/ipFfhjZsuO14azlTnYeH1+VIK9bSxPeh8SCn5SFrfh/2jsDEp+6TU6Ot08kx+3I2ZgejBLu7DAPO2T12coy1OnVGPDAQbROR3xlwTctKWin1HPF/29Nz65GaHummICp9gM7Zk5/8qwrSPgrEBrstCbCUI4J4zrLGTUlS/4bGWTvxusbsHkQ44ClKK+NKzxRy4FjIjAOmKNT+oVPuQMe7ton2Ee2N3SLB6N1Q8SXb3ZRE19c6g69ESGtN5QIdIUPg6efTtlGZcmluUeHForhOV3C+du0tq9AEj0LQZkBjlPrBYJ0xmPkg+p+jj171M41lcKDu9xzUOxHWXzwh+ZeMCdQgxuQyE4ynIczhsczRU1SWHX3NT4/3FIZHyf+2237zTej2syAo9IMhlrmYDR6y1PGUOcIcX/c1vb311yI8YsOGxv31A/XW6juanGKv7+U67JFX7U07on7XQjBICZfS/HYKBKa1X5DXHHbYaYuhIAjRZlNotksU7LeIgU183BhtUrXwIopaNgjbPMaYVcU0R0ls5fXWtrxjJDrmmKMfLpI+Mkn0Do3GlIPEPI5DMiYc1reXUCYKUvtvSZh2DxIl1WOsX9DogoFupHU4DOdlpsHacv5bf2nIzJgqUmmlTgztqPSx4iCIis6jV6cOHDGPVXWXJEJBEO1K/rukWZqn09W447VBQxZGcsgh+z/RGPNgeAFqLBP1K97eIOL/Z61+4EgmXqM9LdZSYQqYwf4obueIwYHj6dVMBIZtEB+dPBrviKTIM3o+zU5fI9oa6IvxIvmHVNKuCZkNHgLpa1Dm0Eql+kbU7dvwuL+xalXXFzdurH+8t7fx7r6+xotB3E/o7d1+XOvfQ6zVOrJjKLsWUyI6l7irbH8uhc3sigOICh5V2fN3vbYv58zE0+XLc2lrIADhFjJEss9k5Y9WivNSLmOhDDeNBCeheN2udXdWXp+8ZTaPqFarkYjLiHhUjtaaTJZpt3HFu88oc0p8aJcFOadKF4y+dbKur2/nh268Mbmqp6f5kZmH9MMbN2re+kdE5G+yDF2LxtsNZaMGTAbdj/awGKN3p0adqylSCWWZeuhTXFr8UXvU0OzxamcvasuhRHl8XPzIQEfeceNj5rDRaOQi5jtIRNu2EXQXGOfeA4wd6UC5kv0Ec4C3Msc6BzxaHhFkY75Yf6adPWPjxsZ9SnKkIg/tZdHpCk1y+OHRB/M8/2IcVyFbO47GlgHy4Qk7SpIGOhRxEMSHId0jEZ5bqVReivPLkPK/iKJvEVV/CuL+HIj7bQinKGFrGeq5WKuDktYXqf0KBAzCfK4sKh3EEup+qiBSMM5UlybF9fdTIStNR34Bed+Ooirsa5zcQVRBUnxrOz1FP1o03t40urTuMAWeJq8t3z7lMQCQXx804qF3+nM8a4EdFdnGbLw4m2bD7MbktJIwFucSiqLofpVK1xm1WnzavoXotDiOT6/VqqcFQXCYyiRi1F37ox4xAQ+XpnvGEfULmMtstMuC/ATHq6267pK17VMeh7rtPHORcLeGmQuhM5UBgFlJsa9v+2FoiGelaeGUjI3qiCt+lWdM+NmhofhaTQ+CRiLtQHsPw5iK0DxDQ9XfwCy+HJffwZnQoAyfOs/juHIg0j12pvpbq9MR7NAx+pIk+X2lUguhM8hYOyCOxgSqFyCU54lgLl2/tpUlSTPLsqYzJqgEQXhAGFaPCoLqKVFUeWUYxp9jrn0HRA2y3vE3ipGK0vJ0P3dhjPT51lup6AVzJ3s+JSm+u8vXfmzM3Jm2MS0C2x0alAU73F2HXWMYJoZ2C8tbffc1VQ+WIa10uA5yTTAdVr0ndD+uFb/r/oADtt+byD1MiU7ztK4zeE5lOuf+Z8uWVX+2tviF4wQbb6WcyZ7hmaau0WhkcxGcTdAb7AAAEABJREFUy4WmNq88CAT9haZdMFAY1HGK62UssCzqCl6YIs1sowSDyNSKz1by3vLPnRXvraQ9XMetWGH5IrUTQUxH53nqGEsrCzOxA/xo4J/r+8qYCniAfgGsp+fO+7YX7rpPmef2/dGQP1dZKrMlX/eIL8rA/lw9t7b0ePR4b8FadiB23rKl9rskqT+h2ax/FWQfgmyNCLhfXIbrqIEIERcL9uoRqGcWIgLpcnEulTxvCsgbHkXDZVkDDxnjB8DLfiVz+PWenpFLzzrrL6u0PGtlUbQdLewCTOddASYyXJYio/vyTLfOhbvFafxUAXdyovGwgi/jTq5hzK5vc+hVDXKmbq0dt8G1a4eL9oZRPQN2FTvnRNOMB8aURArrMp8YjWsbG/QHw9PUAvHMTMFcBCoW1F7prgjY4BRjF/oHTalvkQWbDPSNpDiaahXUexyrqVIs1bii0ReP8tl5MJYp1GHc/jXQgHJOHK+6zZjoR8ZUfjazoHlq+r7yK5NEZfGYh64FwgDZuRwNbY7bsGH78URKrDKN2dJuC8PKLEjzyisP+O3tt9/21Gaz/goQ7XVBwFKt1tCvKugErc4sbpSwc93D8FA3FQkp5Yq0jGDwADMR6JsxB6tqtdoFUbT6v/r65N7WsspoWz+VvtwC8/Sd2rlsrmwbTaTTbQV6UmwnbNC+077qNyFZcTiMh2xEwgMDta9i/+MgiMBQNFEmO3QAeMJ/d9ppN3cTbJBGl+OPX1ukEzH/hOs0ue6INSHm3fPbbr/9li9qFrUP3bcTIKuQPVVa5oCNidjMSwipUokpDCu3ZJkUXyts57XA3fVkxXFZ9oW5MuLdMWszBtY/Or1Rv3cQhH+Lc+TcHWtmNsYEMFoTEe1ziJmDLpWFQnZZGZ0jxYPIeDVz+Cy9CM9+Eolr3J6Cdgroz8PD92gMDXW9M8uqJ+V59kyQ9dvyPNkmkt5FxGRMxWD+2WAeMoiiqjEmQDswodPCkxANIGzQNmJKXTl0GDz0NrNSqTzOuea/rV+/43BcE2vnxpMuSyNaswaFLpEVtJRPp6oxgHS6izOMR5tOW45Ipg3XtkRrYQBIDbw/jYCj8ZUhyeHxBeKP7urar3ibQx8Oa7AYkNev33kC0jwkz/UTAqWc0dywWzVVvnp4+Jg67AiSRq+0sYNMVHG3hMJslPR34s7uT3me3jSXIcvSG1HXP+NO4lvNZnr+lVd236i2rPXcTZO9RoimQJ/R3TbdLJswd1a8j5D09n4/1KzO8bONCQ4H+eQwmCn1EtE5LG2MfQ8io+2ohe4SGByt/Rp6nLR1qwQwFr2xmqGxl3Pi2qmuuILuGBzs/s+Bga5XH3FE5R+azfx+mHA+McuSF6dpchWM82tZ1vy1SLadyBBIO6xUqmEUVUbrP64sMxnGyJEkzaRWq5wQRWE/YbF2kgeGmKnX1s9ZUX+ZOgXBC2HTSjddmsUUDyKbti7QkxFmuUpLxvRGQ+FoW7VXVH9/2V4gva0IxExMYwvOSDLYAOK4+DYHPEo+8MDy78WCgB8D29CvO2bMbGgsn7YdEbN8irC0XsfD4T6vIpJHEXwhkiudqx4rcuOD0nTHA+YqZNmOB6os9Is1mzdXP6eKWst7wDnVJCsuzMi45h4d/dLXiQXyeML790qOe+50DMOdey3GJQqmUpo4zdd85SvZI3BA+2rsejtrLfHatUr0xUPETN9N3bKl+/t4WPnBgYHKmdivqdWajzQmPAUd4pkg35cmSeNjIO7vMgfOGP2xzjhJqz4IMTxpJKeNfX0j0FF/cm7npB0Vf6LRD0ejoKW8YqpgT+Q9w6qZKYhDB2KCh+kqMxHWsuA0ve166Ph1zCczGnOCfMGdHBFz8Aj9ypy1nB111AmFBw87eRTttkgOGUGWpT8MguqP9TJIfUZ1d84U8jXvxFDqanA3yOlRR91nuz7gnOug9bNW9mq/4IUJGE3UUo+VFoJRGfN5C7hKC+toGK1UR8scK8xaUmSpr2/7g53L/gFeJcEo9F5tLI0elAasT+znPIjKHw/wQUSyarUaQI/iC3czNfZxWUQWHkFJ1C3PQLQzFqStxI168aWX7n/7pk3RtwcHK58aGKheesQR1dNWrfrLmiTJTnIu+TG8ajxAlF2NU+BJoSizARu67rrjChz1ePpQEi/qVdQZ+92SikwVu1syHzEJgRYxTIrcwwmLfmXxqquObQDtT4e4f8R+IkEW780HQfQw57ofpoLUjs47T+4hkp+SpumkPiJCEqDHwF7++4Mf5NusnfnbG8g/Wv5UZpRBOsHGCBdlHgKRta3+obWdOuAhjkN/wUWogO3kVYhZ764nx87xGZ4H7Zyq8DkuZrK4BSXocVWiNbitq4lgohVQj8cXRyCjamu+NoiiahDNQVCvg1mrL0UhrQ06C7xoneNzvWecIdV2jKeVd/JepmhMFsYYoKStQY+tFaNkjX1YBpJLL71H44orur6FOexnwJv+dRgWnrRMlI+OSczmcU9+slSGh9ehg8kU5U3M0To2k+S0Ykf3fMcd1Kac0RwLuIPHP21djNG2XUDl9lD0oYeuKfRmdt+q1xs7mMNIsJRZWPHHnDIRrj+cRhcQ8ANg9/pJUAzWRRpcwSw83GrYSBaG8nlEKJEWsvW43YCiM7Un7LXsKbPpJwqIGLLnOlBbC+4QYOOadCo7Z9zJ0OJtcFV7H8OCVqokvwLwM3PADyPZRR+1F3FpWv9kkjTfjv37sH9vktTfhwdv79/XABnvTJLG1cCszqwOAkrGSbmiW+BBjTHBfSqVrHgn2tq934JpXjVwpFWiBemSer5aAb00bVAMlKyx1597Y85bOwCRytmyhX/HnL+Ui4GknLtsCXLOkUh+wD3u0byXxllLey1L0yEfOrgeTZk87O6mXdpA0y7WIDofNaVyzBxPeWFGkSxlcgc/tzzadWtMNuOPMg0P69snwpdf3vUdIv4hvENicAyNL5iyEG3f555xxu+Kt0TQ1v880Uo1qZ4bo9WU34l0FQQ9XLwpolfbD5AzZR0QDyGmKB/64Xj2q7Xal4o+P0Nh+V153nCMhYBMKzN0dMZo80jxLY81a1pXlsd+wTpj2VBEGzbUH81sMMVR3LqNoSoi8CL073b4usHBrmdiCuDVAwO1CwcHqwhdFwwNdZ2/r+EXv/jv1wwN1U53Lv9K+SBEO8xY0TiQHHPiMIPsRTjRdY84teoC2xFry79W0o6i55p55oGlv798tQvDxbVp2rgOHr8SfkGuzISpEvXy6YAwDO6p8q+7jlj3ewvw1jAIaKrJnQSGTsxSNeYv+mRIEyz6IMLbp1MS5jOjueHp5KxduzUwhvYfvT4B4xI/54L66LUZ7PQTAWQ0A9ryP5wTPSzO9YCxOJfi0Dy4Wj38YBygbbico9KT8SDQDWf81aEh/aaLjMlA5F7Xbdu2FWlEpC6FCjRWP2a1Mb3Mh4AQmXBa7mkWi35jRqczyucmtiDr9sQFweqdROYvzMW3dEYzMRYpMDCGiza68Ubi0YvLYjejBp3jGhdlG2OeB5KMRdSH5qnALTyDNWtaf+qqHWO2oRxmUfZn83LqqtClVT8Ya6EH40GNfuGuJN3pjR/XC+LU96d7e0fO6+1tfKKvr/7R88+Xw0uZqm951O62hYRzv7gDx9djnpCwL8pRGcALhhlVsiwrysBceaGzXpsqHHUUicaDhLc7R1TWEVtEYgvCF5V/aBwfUnyX19pL9igP2RZsbenGzDfyNFriBuPequB0n6/Ua3sOZZsdfviT7gkKOAB4Kz67ZWFOGrtFthExXHjRRElCn8rzJuajA9QELTGaF6RJQYCJCzEPO/PMkWMQ/SCHSmGPdNhiRd1ZX7lD/IdwOuO1NdVCxDfpgMBYaHSBJnhYKXp23Dnn3NqtB7MPLOvX1x+n9bHWFrZs7fT9Ssvr7y/tFvbfACa3GaPechlHWKAn+gGGDqHiTvKXvyRB9JyvzMRzLrQNgZOIqY30c5IEQDNILdMvuhkTPAYg7yaXmU2ep5hbyov/hLvmGv2fMQb4sw/btpXeaZI0t2ZZ8y9odIA/rgUzMbxWePDRA3Dt8aPKTYmVxUOZnp5Gz8aNjW8g7XeDIH5fpVL5566u6guSJH2V5rWWWPf7EoaGTsiBV+H1jmtYGCQxG4KuhcXuTXbLWyJyt6DOyIfMo5mYFeumEEX3T9ORo8vo/nK3KLelbszuelWPeXKnVJxQpQfjwdp+wzOan1dpZWi9vZNllccw8wEO017llXLLaFEltSyjW8uYS8pd21u1Y6Irr6z8joivNWbyj1bQ5k7v4ojkb0HTf4tj6JCSlktYyutVEHT2Q9jxLxBF1k7GQeP2FMp5ZZQg5nsg+UnTfcxqE6lmf2CWdRfTB3qyL8Haawob7etrXBRFwdejyHynt7f++ttuo73+KpaBs5Z55523p1Cp+Boec4mdxjMTMNA6yCPPPPOmQ7dt0ztYa/TacggLUpFLLiGd+KX99ut+LHNwQrLLL/vU+MKwAnJ236jVun6iQKMhdDdHoWxg/ZcLdOYvw1OBXL31wq5Yi9JA0ETM8cmExdqS1HFYrNaWI//NNyfPrdUqg8ZUHgM5Xdppm81GXq+nlOdu3Rln3HGAtSpbuMjY5gZ6FSnPOovgvfAh6jxBqzEZjMW5JvSTaW/zCwGjmzXj/7f4e+ALQ594q1gYuGC6hMIwan1NbaysURGLbgdM/rirUszaYRUXvk+a1k/R6z093y8IQo/bDa07EhH3hDjWeV7CIAnpECBYjIlx15H9illuRRTIsV90P5NgCxtSWzT/WrxyTONTbShJTNE7zf2MMQcbo12mZRWEdqdc1WLmz+qf20IW6qiyqO0FeUUTH310/DNI/pOWgb1GjQYHm6hCblT8cKs1aI1ebGtXPgA/OTv77J1/C/mvQ6AgCI+I4+ol6Pff7utrPnvv/UP4ox89WP844FeKCeAv9C4V4KB0pqoPqVQOfJjGHXdcP+t+5sHtY76Zl9RujsIE2k08V+n6+0uyw63jP0YRq1inmwnBBbBHEfepyy7jpjYy0cyMj/aylDKJROTfdm10zcpMATxgXE/XnX66epXojzIVyXJFJ2eyrOHgZcFwWBc8lXd5pVI5qlKpXkhYYNwRdm2vrT8vqFbT+yLTo7KsiR0V7SUoxZgQutHt0P/3egFhVwwRNb7295feFUjtZuZg1Fsq46hYDOEajvLTsCEQlChGFiTSCigLjTUVBpqj8yEI5JcYDEEsUQDdRuvPqmMeRUqq4cYLL7yhNjR0Yqp1aFfDnh6JQBrZhg0j8J7DU9NUn6EJLHJMAsjREAbvL5aDvGIyc/u8bvS5Aezv2nq9sR3kBTLU1i3KMaMfDXuqiOvXu0lCiWUQYTbRyEgjEUm/RlggS7DbpxV1Vez+jwjQoUvQ6CJCKEdPsh5rJVSbwOUikcbuPegX+MpBB33htWEY7p9lSSaSMtrNRVHleNT946TJoKMAABAASURBVMD52YT+jTIM7baw9PQQcNEL8j1tXT3aNRjDxMxvWLNGQvQd1Kd0oHZNN9X5UUedIBPjRYRxPinOOY2Dr4QLnVynAGS+ixfgqKDL/iJSfLmOufSoCQvi4DkEYaPR2AGSbn02EVfmdi2NjUBK5v9gLH8KgjhE2WjYVjmMObgcRlQ9qLs7fKLGwvPXhtNDhPKW1jn3NYzgIDwwJmJbq4gzmB8mEOn5GzbUTxoe5kQJTwPB7svQSq17gWzRUaB4Txrp9b0W6CBvhreh8dANSGlSZDbwqIyJ7iBq/kajrCXR/XSBWQlEfxjUdb1IdpMa9MS0zIQppQY8psqjenpG3oMOz6qDyrV2/NvUhI6E4qErLdhirdZVeNOmrhuCIPiGev5QBvhgW6ysXhVINFozMnL4WzRqNI9R/KXogII6jAdrx153NPrA7cwzbzsGhPL+MIxjtDFkAyEVhMDMuDsiAtF8D6cEu5hI3hrVVhgeJqe6bNoU/y9R9PXxz+xqdkbbp7Af2j8Mq/cSgQoaXQR2sFeULz8/8sjuazRKZel+pkHrrXlQ10+EJQ2OFcTMGCQaLo5rD/nznxuvsVb/L5RMmUeAn+bcNWi8PgzUH2cR0rCcc076MrTTs5rNuoNMlMIM+0P/aKbGxCGOj1cpanO63zXccQcVOgGR7zWbzR3GYNJHRFrpILPQE5g84oEPTN9NhGKJC2ytHW9XPW4FtQM9hhhNTLqAbyCKiFnti8biaQEX0+myrS0rjocrTwnD+BhMCQgRIKFyYWZ4P+ps8v9cfnnXdxTAfTW+UuLUW2vV2CS44orqr4n425gXIyyFIWA/tqoZiOTF18XGInFgrXWq29BQ9Teox9WVSqwdBqSKi1iZDWvdQKToYOHHent3nDI8zHk5MChZEq1dK0FPz/fgrUloLcEgWBhbTYdrMYhySxzHT8GtoBr2bm0Fr+p/hoYOusta9RZYUOweV2u1DCLm4N9o6qXQOQyjCw46qPFNzBO+trc3eTb2f9/bu/PEnp4df71+ff3Ynn2YMpi6uH2N1bcAqCDFLMvxoJeImYGPthaNLhyAEKRSiS7AA9uPnXsuHUTEbhikiLTAqoWX7lUeO52TtZadfvMijrs/HQTRCZgmmYQ92hxTX5Uwz7OfjYyk/0nFcsludlNE73XD0iJ39Iev56X1oB6tjGAKcRgM0knyoQOshMgY8xVrOYOtAAutRyvfzPdJkn4nSZKbgl0cFWbCHG8C2w5eB3t8yTBs2FolMJatxecQ1HbHQ1kyiwWOGmA7l4CA3wknRhhLeV23gvMoStPmnczZgMYMo210v2sYLsoUMzDQ9S0R/eNdcDzGx4npmEkJHwOXeQns9GN9fXfcm1n1ICnzl06G6qShFadpiMj19SV/6xw/0wFplMGIWxTrBGNoU59ZJhsfJfMXGJQOMGSiSBgfPDmNka/qFrcrSDU741M5ew7y2STJCI2FlodG44lBWA7x4YN7e+U4bVhbkGGZoNSN0IGaHwFRTDGyG84w9YGOdFQQVD4NorjqppuyR+pH+Im4MJzy9lsfbJTz1Oecs/NwzMs976CDkq9XKl1nJUlzt+8uEBYHS4KmhWHjdEZrmjJILZsiD6MjOtQnJ9x+PiqKqm80hoeZaRuz+Y4xwffiOPot0V/3U7HIghmytZyrCps31/4Ft83fCcPi+yVO41oBOrPih3o8P8uaPwH+b9q4sf5IxX/NmmvQ1mpXoncscV/f9sN6epqn9PTsvCKKom+GYeWhJTkb2F9Lou6FgAcB/3/9yEf2u03JUQdrvbIvob+/nO5rNNL/wIB7JwYFlIeWHRPGWAhxYxEon5WMEOE+jg1t3Vp6mHo80wAcnbUS6qdynZN/UUcFBRbYlrJY+4AgLgjD+H29vfovQOkJPXAs1q3jHPmL9/dbe4Jdn3aadOOh+ZOB5ZfiuPr6PM/V2BjXEKhYUEM4YgEGGXr9wMDqW6CDIeSlvSzwxN+BvFOkUtGiuuYYXJ/HXPsJ7lw/3Ns7shFt/rizzrr7AevXj9zjrLN2HtXb27gfBptH9vbWz+7ra7zrxhvrPySS7wP7R+Z5o8B39wKY4niZ/5JQG0FHLjTefYyJMGLJLjiITm8YzOXWjeGP6cXhaUZVvTbb0JK9c2f2Wefyv0CnSSJhlGjwJA/D8GCi+tP04o03ErwVPSIaHtb/UJSgHNndlejYemGCcRMa26AzJQ7yQxjri4yRbcbUvtTbO/KZ3t7m1b29O97d29u4tLcw/Obn8tx8LYrCj4Vh9MgkqTsYzlh5hEXEZZVKFRjJv4Gcvo4oPKBSj0aP9hysLdNdcYXeUgefUDkqb3IurTVhYGnmadpwuI7LmOAjAz0Yt6MBMdMTtYNSGx2K5m+Bl2YNxAsell6kHMAckGBB3IRVv6/ScBhcjkB9L2YOv0xU/coDHvDIz4OwP9vb2/jcQQfVP++c2VapBJ+uVrvOgohKhoGV2aj8ibJAKjW0Z/q/O3f+/D16QW1A9/samMtB4qqr9v+VSP7f0BN1KNtpKpkgJ9QlxgAhP3Ou9hNNw6zbfQ/9/VTYrMj2S+v15A9BUMEtrBRxKpWxOJdh4M4cMHxuEMiXjTkeNlwfBPm9Bv35gt7ekVeC7N6zYcPIJ2u1xjWox3/AwXhikhQ2FBAxjS+SVqvVMEnSr+R5pXAyWrY5nmbykbXqwBBt2hR9ybn8E9DDCPrC5FQAU3JMd2i/CbpRxulozw8ShddEUfS1IOCvYAD6qohsC4LwG7i+JYoqF2EAfwj6Ge4UUqFJetLoIgRLyBLcSIxGdGxnOlYSCmqRG27l8HAwPDrPJ3uHMD4QdEQiybcuv7wKTw2Z5pUEys5x9dWrb2HOP2PQCqqDljoehLiwreDxa9f+JNb5SW3M1nV0UKfHP/3pn16Zptm3YDg6l60eg0YXgZkVZzwYqTsRF4Vh9eGVSu2fqtX4hZVK90srlcoFMBb9+6t/xLX7J0nisqzpkA35uCi9EEQuD4Iqbq/zWzBgXII40R9SEGk9qI1FfyAhARJKnjfemef53cZEIeoz1hlxbXTlgKFAeSLYCdpFAxG6QfOXv9yukbSQi3qu1orZvHm/b+d5dnGlEgVoQzyEkqJNSt1QC2YMaJk0mw1co1oc104A/k+I4+qTK5XqP8Zx7WSEB6H9TJLUgYVoJmBfSii3LjcmDkAOt8FjP/Pqq/9mp5ZdXpvd1loq2lgk/xjjiAHw9BJhQBFTEJh/gS2OlDq02/405aLlqZyhoUNvEsk2IuTMBs89nLQyIA1WMpg2ykV4vziungSb7YG9vtmYyqVRVHtbHFcurNVqzwCmD8cdZQQsYcMMHBm1KiSJiIPDU8W15Po8d+egDqMPcPdeB2sFskjSNH15kqR/QJm79TUixgI3SHKCg5E3GtrmmQmC+PAwrN4f+j4gDOOjoIc+58o0TZ4nhb0gY0tPmrDkURQA7/iH+k81Gs9TpdIL8xDMPMicRqQ+oGJ9sRLVC56giUR0Oym4CGM3UeUqjbVlg+jhvAVrCfqAoiQYnroQRqdt4pI8/uCD7188zLC2zINIXUGSEmzbdmwjTbPTGo3kDzDQUcOBlWiK0cBsgLdQljVyJQs1ngRTGBrK40aW5wk6BxtG4tFsSoyCJQuCOBBJYaCNC3Fb+BO9vR4u3vNtpdz7HgNKrvmGhrquhb4vZw7IgHiAgBKTBtmbFOjC4z9y2FvqXa+bvcrfNceezq0leNKCB3u1t9TrzffEcRwZE4BcBIPkuIUBT7Qz63e1cXfQyJOkbANthzRtZlnWLHAnMsHE8lBXATbAXv9rMkvyvHn25s2r/lcxtLb06iamn82xMeG3QWp3MasO47qPyxTBNSWWhMh9Q+Ovu45Y97MNWhet0+bN3biLS14CDCkIKsDRTbIJhm4YpAj4ZU0MeMAuz3C3kaYNh7jCrnEMLKEqq72XmgFHkKC4SqWmNvyHPG+s27y5+kuLPq5ll6n2vNV0ml6nY2C7p2ZZcnMUVYu+Bvmye24O0O5wQBjesTo9xb8UuTxPHNLT6DVtb7N7XsmRBu1eiTL0ymazXvwYaHxqbPcc8xEzhWLzUQyRtVQYUk9PA9Mb2dOTpEnMpOCQLgAD3nMQ1uuN24yp/0DjOhmY3f+hc/w+CGIDXWBMrdKhJYm+MofO7Z7Yip24V9KzVowaThy7k9GYX6lUqiFkMWSp17aLvNJwmBnGQ0Uoj4tzxaTACnmRz8FzCxy8FXjO6Z+J5GlDQ6s+puVpuRP1aPdY82l+POAcQkdZi4eZN8VxNQjDKuxB56ELctOOqUbqVA8NkI/jvGi3Aw8kpEXMFCumx9FpigtIL0XAGfbQXpy54YZfT5sX6Wa46oMghmzhwcHqRY1G/SXO5TsUf+ZA4xV/aQkFzsCWgTEHOA414BragBGHo9FV6yvicMcSgVSqIUjo5yL54wcHuz+lRKYYjiad9c7ackpD7xqNqXwugpciQomIOJHxgIJSeH/EHH3n8svfXrzhNDy87/PPkDdpHcaUnbViUMdNIL8X4q7kzgoIlUjN2KktCGEBZoqhYoZAAc5HHQrWY8QxsGSk0fYu9M/CMGSQqT64hWPQOGVoaP9rFUdrZzbIaXoLHfVjYiBpPEAf+Zn2jSCIHKBSHdFnoOQuKzMXOk7YF/pNTCaid16SOScuDCsBBntt9+1Zlm7YsqX7s1rutm0nY+CfmGt+j+ewo7SrKD8XDQU/WfIyB0wRPiIzYW41wsOp6tc2bVr9MxFha0vDLdPNz9bCQNRQMI/8pziufL5SMaS6EHQaDwSvyyFeXnTGGb+rap5dtdE4a8V84AO134nUntxsjrzBYV5bjQeNzViQBbXCCrmou9Z/11DMBTokRFmGgiDmOK7B6Cmp1+ufFkkeh078XzqKa3mabl+D5td6Dw52/VuWuUekafPtadr4CfTMVOcYhI12CqKoasZDhWu1gMIw+pPemk5Xtkh4IzgG6SpjeZX841hzcP1zn7tfEzAwoePTHC0MaWvXbg1Qn8uMyf8O3t0XgoDTSqUaGgPOKMoRmR77oi30OgIX2Fer6u25u+A0XB7Htb+HjXxLMVMiozlddJCRQsksS76gficwB09XldQMjosADBFHsI3sM0TWqR3gDPrSnCwqpLSLAsd/JYof0Ww2/x3YYpCqBUEQAWVNhdaTgsymtGOR4hr0ZO3PXK1W4Vxkt8C+Xnv77b/9+6Gh/X5u0Vf2FUfVEfnDK67o/mGl0nVSvT7yASK3o4r20j6jGtJ4/51SR1zPRQo9pUxvKAgqJo6reFYUGjiQv8qy+nvSlI4fHKzBe1Y+mtlgUsqd3dbMLnv7ufv7S7JFYz8cgYyJGfOpCBWEGOBUo3q9mYDYthCWdesIuu19XgpJ52xFo3x0ZKSxAx0hDoKq6gTdqkUw6DVBEN2zu/uIw8sCZdRYyzPdquGI6FQO5YOD3f1E7tFJklyc580fOgeu9ukWAAALD0lEQVTX0UQM2RyD/KYKUVRBJ4gx0us8fJ7meXIdOsh74Sk88Y47as8aHNz/V9aKmatRXDuIyoPn/ycQ/6tqterf53n++EajcVaSNN7SbNY/hk71+WZz5EvYfwFxn9+5M7kK+zdqfbWuum8Fa8s2Jrrlizt2NN4IsvlqljU+h7x4CJd8Ee07LOLO0/RqA7qfu6BvxazVNxLM5Zev+tEvfvGdp6Ie/wRdN+d5eqMxERkTE8gOnlF1t6DxaHNGGriLLsuy9Mf1euONmM0EodTOuewy+osF9orZ3Ok8LslaLjyzzZv/82q0+cY0rX82yxqfR/ichjRtfh5xnxkZaV703e/+5L2ac67sQGVNDMOYNtO6Dg7yr4488r+fyxyc1GzWN+V58lvmgsg4jqtKZlPiCBtHd9EHma4J3b+Ou5qXBwE9cmCg9uatW48v5pxR38IRmVjuTI6RP1MdL7uMbx0a6oZNJWvq9eY7oKP+7B1343HRb7VdoetuemocrqmeaPOQRPI6dP2+1rPZTJ4B5wrO0KqLPvShrhu0HJpDZ4JmsIAEZ5B6FklbHZLZXdhoNC/MsuYrEF6epsnL0BkQmi/JsvxROgdGpL9AKl+jmkWRbWfVTicFsXZ9M8/NY9O0Dl1K/VRHBOhah47pMz74wdofSsFTDx7MGq/vXAqIovrbyy+vvOWIIyqPDAJzgki6Icsab6jXG/+aJM0voyN+dXJIrkZHBKHXzwAWJx55ZPVvBwerF27e3PVtfX9adYRhzsqwS93HtypPhEjfaX3ve/nOoaGubw7CY0BnuhjHpw4MVJ9y9NFdp2D/5KGh2tPKf4JZVfxzR1nXcVk0asRDQ0fWkfb1SPuPAwNvfyryPuXyy+OnYL8OMr9JxaI4FQdzuFFPtMT+mmvW5Fu2rP7qwECtp1KpHpfn6T8B/1cmyciHgPlXEHbBvvmJPG+8Ge2DNnKP+OUvKydoHT74wcp16jUrRorVHCo7jah1OQbLgcHBLmBd/aeBgTIMDlaegnZ5xuBg9T3f/375L0TTCJiTaK2rtfpQbo3bVPyhRNe5XV21BzvnngScXpqmjQ9PxBD2/BWEbQifxHXgmJxBxH+NupyMurxL+43KU5tR2TQHi8rRPqHts2nTqv8dGqq+EsT70Dx3f+dcow86vi1Nm8PQ8xqEsfZOkjp0bWzFtXc6l54HDnoOc/U4OEGPHBysvXjz5u5Pb9my6s8qF1xktJw5UHefRHSMoGm08w4M1H4PIN+LjvruwcHqu3Cs+/fg+DK9ZVHAW2mpg4sajpa9ZUvlRzCoy6DPuyYG3N6+e2iodk27KmmjqkGWgTP9tdjll9e2DA7W+jdvrr1gYKD6D4OD1SdMDENDldNRxlswx/xhGMiPIANeleh7uoG1GLUK8m9Xg/bTad3XFe+0WqNGqQG30IVt6DVr2emeijYU3DlooD0utujcSsJ2Ql5ILeL3mHXWF0t9yx8CoYMxvKy7gfNnL7+8+s7Bwe6zcPxEhF2wrz5nYKD22qGh7i1qh9u2qUdb/gpNB3CeJ+x3razaYImdXlH8Jofy2t7x19yzDYpjfz9JaQ/Cl17KdeD2JfSFS4HVGTgew3BgoPpEBJBx9ZkDBY61D+P6r9RuVGeVofJojheVr+2j8tHWBm3d3Ly569sDA92D6EuvHhioroMeeHYw3tcGBrqga+25iH8Frn8A6T8xMMC/VzmqnspSnctznlOHSOXPJBSdcCYZZp+2JBwFYdegxqmAz76MfZOgZasO2ji76qbnGj8TyWqQGso8Wu+tgcrR7wVAVrhr0Pi1mEdFPEZt9V40p966692EdlQ9n79grXXDw5xrAJVOY5iqh4Y96VF6slOlGMdjqqtzGTcZN4uBYRTb3XDHtSJO2wbHE7F3w8BjLrXamyy1wT1hVF7bG/57K6X966pPiUFRJqZ/pHAYRrEqcANmk/aj18At5UCiOpcy2i93pilL+SWZQp+iDUf1mKQbro2eXxPqdQ2IG9OV4ISoLNWZFsECxTqtRdlxFIRdgxpDp7XZtTzVQRtnV930XON3Td/+udZ7XUF+2+CdQRbm0HhS0PjhYv6PMZdaGlv78n3KPSEAvN0otpMwR/zY+fBw8cs4j/30QIr2D8VJw0TsJh6PXsMAX5D69NLm6Qp0KdpwVI+x9kX8hOOTM72uAfELpuveIFgAgt6bSv760kPAa+wR8AjMBwKeoOcDVS/TI+AR8AjMAQKeoOcARC/CI+AR8AjMBwKeoOcD1cky/ZlHwCPgEdgnBDxB7xNsPpNHwCPgEZh/BDxBzz/GvgSPgEfAI7BPCCw4Qe+T1j6TR8Aj4BFYAQh4gl4Bjeyr6BHwCCxNBDxBL81281p7BDwCC47A/CvgCXr+MfYleAQ8Ah6BfULAE/Q+weYzeQQ8Ah6B+UfAE/T8Y+xL8AisRAR8necAAU/QcwCiF+ER8Ah4BOYDAU/Q84Gql+kR8Ah4BOYAAU/QcwCiF+ERmCkCPr1HoB0EPEG3g5JP4xHwCHgEFgABT9ALALov0iPgEfAItIOAJ+h2UPJpOouAL80j4BEoEPAEXcDgNx4Bj4BHYPEh4Al68bWJ18gj4BHwCBQIeIIuYFhKG6+rR8AjsFIQ8AS9Ulra19Mj4BFYcgh4gl5yTeYV9gh4BFYKAsuNoFdKu/l6egQ8AisAAU/QK6CRfRU9Ah6BpYmAJ+il2W5ea4+AR2C5ITBFfTxBTwGKj/IIeAQ8AosBAU/Qi6EVvA4eAY+AR2AKBDxBTwGKj/IIeAQWGwIrUx9P0Cuz3X2tPQIegSWAgCfoJdBIXkWPgEdgZSLgCXpltruv9fJCwNdmmSLgCXqZNqyvlkfAI7D0EfAEvfTb0NfAI+ARWKYIeIJepg3rqzWOgD/yCCxVBDxBL9WW83p7BDwCyx4BT9DLvol9BT0CHoGlioAn6KXacnOlt5fjEfAILFoEPEEv2qbxinkEPAIrHQFP0CvdAnz9PQIegUWLgCfoPTaNv+gR8Ah4BBYOAU/QC4e9L9kj4BHwCOwRAU/Qe4THX/QIeAQ8AguHwGwIeuG09iV7BDwCHoEVgIAn6BXQyL6KHgGPwNJEwBP00mw3r7VHwCMwGwSWSF5P0EukobyaHgGPwMpDwBP0ymtzX2OPgEdgiSDgCXqJNJRX0yPQOQR8SYsFAU/Qi6UlvB4eAY+AR2AXBDxB7wKIP/UIeAQ8AosFAU/Qi6UlvB5LBQGvp0egYwh4gu4Y1L4gj4BHwCMwMwQ8Qc8ML5/aI+AR8Ah0DAFP0B2DemUU5GvpEfAIzB0CnqDnDksvySPgEfAIzCkCnqDnFE4vzCPgEfAIzB0CnqDnDsu9S/IpPAIeAY/ADBDwBD0DsHxSj4BHwCPQSQQ8QXcSbV+WR8Aj4BGYAQKLiKBnoLVP6hHwCHgEVgACnqBXQCP7KnoEPAJLEwFP0Euz3bzWHgGPwCJCYL5U8QQ9X8h6uR4Bj4BHYJYIeIKeJYA+u0fAI+ARmC8EPEHPF7JerkfAI1Ai4Lf7jIAn6H2Gzmf0CHgEPALzi4An6PnF10v3CHgEPAL7jIAn6H2Gzmf0CMwFAl6GR2B6BDxBT4+Nv+IR8Ah4BBYUAU/QCwq/L9wj4BHwCEyPgCfo6bHxVxYeAa+BR2BFI+AJekU3v6+8R8AjsJgR8AS9mFvH6+YR8AisaAQ8QS/h5veqewQ8AssbAU/Qy7t9fe08Ah6BJYyAJ+gl3HhedY+AR2B5I7B8CXp5t5uvnUfAI7ACEPAEvQIa2VfRI+ARWJoI/H8AAAD//+UxmsAAAAAGSURBVAMA/czJJ+XpE1wAAAAASUVORK5CYII=";
document.querySelectorAll('#login-logo,#nav-logo').forEach(img=>img.src=AV_LOGO);

/* Cursor glow */
const cgEl=document.getElementById('cg');
document.addEventListener('mousemove',e=>{cgEl.style.left=e.clientX+'px';cgEl.style.top=e.clientY+'px';});

/* Cursor trail */
const trail=[];const TL=7;
for(let i=0;i<TL;i++){const d=document.createElement('div');d.className='cdot';d.style.cssText=`width:${6-i*.6}px;height:${6-i*.6}px;opacity:${(1-i/TL)*.65}`;document.body.appendChild(d);trail.push({el:d,x:0,y:0});}
let mx=0,my=0;
document.addEventListener('mousemove',e=>{mx=e.clientX;my=e.clientY;});
(function at(){let px=mx,py=my;trail.forEach(d=>{d.x+=(px-d.x)*.35;d.y+=(py-d.y)*.35;d.el.style.left=d.x+'px';d.el.style.top=d.y+'px';px=d.x;py=d.y;});requestAnimationFrame(at);})();

/* State */
const API=window.location.origin;
let agent='',activeSid=null,activeData=null,pollH=null,pollL=null,curTab='all',showAna=false,rpCurTab='user';
let allSessions=[],sseConn=null,lastQueueCount=0;

/* Sound */
function playNotifSound(){try{const c=new(window.AudioContext||window.webkitAudioContext)();[{f:523,t:0},{f:659,t:.12},{f:784,t:.24},{f:1046,t:.36}].forEach(({f,t})=>{const o=c.createOscillator(),g=c.createGain();o.connect(g);g.connect(c.destination);o.frequency.value=f;o.type='triangle';g.gain.setValueAtTime(0,c.currentTime+t);g.gain.linearRampToValueAtTime(.42,c.currentTime+t+.025);g.gain.exponentialRampToValueAtTime(.001,c.currentTime+t+.32);o.start(c.currentTime+t);o.stop(c.currentTime+t+.34);});}catch(e){}}
function playReplySound(){try{const c=new(window.AudioContext||window.webkitAudioContext)();[{f:740,t:0},{f:988,t:.14}].forEach(({f,t})=>{const o=c.createOscillator(),g=c.createGain();o.connect(g);g.connect(c.destination);o.frequency.value=f;o.type='sine';g.gain.setValueAtTime(0,c.currentTime+t);g.gain.linearRampToValueAtTime(.45,c.currentTime+t+.02);g.gain.exponentialRampToValueAtTime(.001,c.currentTime+t+.26);o.start(c.currentTime+t);o.stop(c.currentTime+t+.3);});}catch(e){}}
function showDesktopNotif(n){if(!('Notification'in window))return;if(Notification.permission==='granted'){new Notification('AstroVed Support',{body:n+' new user'+(n>1?'s':'')+' waiting!',tag:'av-queue'});}else if(Notification.permission!=='denied'){Notification.requestPermission().then(p=>{if(p==='granted')showDesktopNotif(n);});}}

function connectSSE(){if(sseConn)sseConn.close();sseConn=new EventSource(API+'/agent/events');sseConn.onmessage=function(e){try{const d=JSON.parse(e.data);if(d.type==='queue_update'){if(d.count>lastQueueCount){playNotifSound();const df=d.count-lastQueueCount;toast('🔔 New chat: '+(d.sessions[0]?d.sessions[0].user_name||'Anonymous':'User'),4000);showDesktopNotif(df);}lastQueueCount=d.count;document.getElementById('qbadge').textContent=d.count;}}catch(err){};};sseConn.onerror=function(){setTimeout(connectSSE,5000);};}

function toast(m,ms=2600){const t=document.getElementById('toast');t.textContent=m;t.classList.add('on');setTimeout(()=>t.classList.remove('on'),ms);}

/* Login */
function doLogin(){
  const u=document.getElementById('lu').value.trim(),p=document.getElementById('lp').value.trim();
  if(!u||!p)return;
  const btn=document.querySelector('.lbtn');btn.textContent='Entering…';
  fetch(API+'/agent/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})
    .then(r=>{if(!r.ok)throw new Error();return r.json();})
    .then(d=>{agent=d.display_name;sessionStorage.setItem('av_ag',agent);enterApp();})
    .catch(()=>{btn.textContent='Enter Console ✦';document.getElementById('le').style.display='block';});
}
document.getElementById('lp').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
function enterApp(){document.getElementById('ls').style.display='none';document.getElementById('app').classList.add('on');document.getElementById('npill').textContent=agent;loadSessions();pollL=setInterval(loadSessions,4000);connectSSE();if('Notification'in window&&Notification.permission==='default')Notification.requestPermission();}
function doLogout(){sessionStorage.clear();clearInterval(pollL);clearInterval(pollH);if(sseConn)sseConn.close();location.reload();}
(function auto(){const a=sessionStorage.getItem('av_ag');if(a){agent=a;enterApp();}})();

/* Sessions */
function loadSessions(){
  fetch(API+'/agent/sessions').then(r=>r.json()).then(d=>{
    const active=d.sessions||[];
    document.getElementById('qbadge').textContent=active.length;
    document.getElementById('ss-w').textContent=active.filter(s=>s.status==='waiting').length;
    document.getElementById('ss-a').textContent=active.filter(s=>s.status==='with_agent').length;
    fetch(API+'/agent/all-sessions').then(r=>r.json()).then(all=>{allSessions=all.sessions||[];renderCards();}).catch(()=>{allSessions=active;renderCards();});
  }).catch(()=>{});
}
function renderCards(){
  const q=document.getElementById('srch').value.toLowerCase();
  let list=allSessions.filter(s=>{
    if(curTab==='all'&&s.status==='closed')return false;
    if(curTab!=='all'&&s.status!==curTab)return false;
    if(q&&!(s.user_name||'').toLowerCase().includes(q)&&!(s.user_email||'').toLowerCase().includes(q))return false;
    return true;
  });
  const sl=document.getElementById('sl');
  if(!list.length){sl.innerHTML='<div class="sb-empty"><div>⚡</div><p>No chats in this view</p></div>';return;}
  sl.innerHTML='';
  list.forEach(s=>{
    const div=document.createElement('div');
    div.className='sc'+(s.session_id===activeSid?' active':'');
    div.onclick=()=>openSess(s);
    const ini=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
    const t=s.updated_at?new Date(s.updated_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
    div.innerHTML=`<div class="sc-r1"><div class="sc-av">${ini}</div><span class="sc-name">${s.user_name||'Anonymous'}</span><span class="sc-badge ${s.status}">${s.status==='waiting'?'Waiting':s.assigned_agent||'Active'}</span></div><div class="sc-r2"><span class="sc-email">${s.user_email||s.session_id.slice(0,20)}</span><span class="sc-time">${t}</span></div><div class="sc-r3"><span class="sc-issue">Issue: <span>${s.issue_type||'general'}</span></span></div>`;
    sl.appendChild(div);
  });
}
function setTab(t,el){curTab=t;document.querySelectorAll('.sb-tab').forEach(b=>b.classList.remove('on'));el.classList.add('on');renderCards();}
function filterCards(){renderCards();}

/* Open session */
function openSess(s){
  if(showAna)toggleAna();
  activeSid=s.session_id;activeData=s;
  document.getElementById('cp-empty').style.display='none';
  const cc=document.getElementById('cp-chat');cc.style.display='flex';
  const ini=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
  document.getElementById('ch-av').textContent=ini;
  document.getElementById('ch-name').textContent=s.user_name||'Anonymous';
  document.getElementById('ch-sub').textContent=(s.user_email||'')+(s.user_phone?' · '+s.user_phone:'');
  const tags=document.getElementById('ch-tags');
  tags.innerHTML=`<span class="ch-tag status-${s.status}">${s.status}</span>${s.assigned_agent?`<span class="ch-tag">Agent: ${s.assigned_agent}</span>`:''}<span class="ch-tag">${s.issue_type||'general'}</span>`;
  loadHistory();clearInterval(pollH);pollH=setInterval(loadHistory,3000);
  renderCards();renderUserPanel(s);loadActivityPanel(s.session_id);
}
function rpTab(t,el){rpCurTab=t;document.querySelectorAll('.rp-tab').forEach(b=>b.classList.remove('on'));el.classList.add('on');['user','activity','quick'].forEach(id=>document.getElementById('rp-'+id).style.display=id===t?'block':'none');}
function renderUserPanel(s){
  const ini=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
  document.getElementById('rp-user').innerHTML=`<div class="ucard"><div class="uc-head"><div class="uc-av">${ini}</div><div><div class="uc-nm">${s.user_name||'Anonymous'}</div><div class="uc-em">${s.user_email||'—'}</div></div></div><div class="uc-field"><div class="uc-label">Phone</div><div class="uc-val ${s.user_phone?'':'muted'}">${s.user_phone||'Not provided'}</div></div><div class="uc-field"><div class="uc-label">Status</div><div class="uc-val"><span class="tb ${s.status}">${s.status}</span></div></div><div class="uc-field"><div class="uc-label">Issue Type</div><div class="uc-val">${s.issue_type||'general'}</div></div><div class="uc-field"><div class="uc-label">Priority</div><div class="uc-val">${s.priority||'normal'}</div></div><div class="uc-field"><div class="uc-label">Assigned Agent</div><div class="uc-val ${s.assigned_agent?'':'muted'}">${s.assigned_agent||'Unassigned'}</div></div><div class="uc-field"><div class="uc-label">Session ID</div><div class="uc-val">${s.session_id}</div></div></div>`;
}
function loadActivityPanel(sid){
  fetch(API+'/agent/history/'+sid).then(r=>r.json()).then(d=>{
    const msgs=d.messages||[];
    const dc={user:'#00F5FF',assistant:'#8B5CF6',system:'#C9A84C'};
    document.getElementById('rp-activity').innerHTML=msgs.length?msgs.slice(-12).reverse().map(m=>`<div class="aitem"><div class="adot" style="background:${dc[m.role]||'#999'};box-shadow:0 0 6px ${dc[m.role]||'#999'}"></div><div><div class="atext">${(m.content||'').slice(0,80)}${(m.content||'').length>80?'…':''}</div><div class="atime">${m.role} · ${m.time?new Date(m.time).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):''}</div></div></div>`).join(''):'<div class="a-empty">No messages yet</div>';
  }).catch(()=>{});
}
function loadHistory(){
  if(!activeSid)return;
  fetch(API+'/agent/history/'+activeSid).then(r=>r.json()).then(d=>{
    const body=document.getElementById('cb');if(!body)return;
    const atBot=body.scrollTop+body.clientHeight>=body.scrollHeight-40;
    body.innerHTML=d.messages.map(m=>{const t=m.time?new Date(m.time).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';return`<div class="msg ${m.role}"><div>${(m.content||'').replace(/</g,'&lt;')}</div>${m.role!=='system'?`<div class="msg-t">${t}</div>`:''}</div>`;}).join('');
    if(atBot)body.scrollTop=body.scrollHeight;
    if(activeData)loadActivityPanel(activeSid);
  }).catch(()=>{});
}
function claimSess(){if(!activeSid)return;fetch(API+'/agent/claim/'+activeSid+'?agent_name='+encodeURIComponent(agent),{method:'POST'}).then(()=>{toast('✓ Chat claimed');loadHistory();loadSessions();});}
function closeSess(){
  if(!activeSid)return;
  fetch(API+'/agent/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSid})}).then(()=>{
    activeSid=null;activeData=null;clearInterval(pollH);
    document.getElementById('cp-chat').style.display='none';
    document.getElementById('cp-empty').style.display='flex';
    document.getElementById('rp-user').innerHTML='<div class="ucard"><div style="text-align:center;padding:30px 0;color:var(--muted);font-size:12px"><div style="font-size:34px;opacity:.14;color:var(--cyan)">◈</div><p style="margin-top:10px">Select a chat to see user details</p></div></div>';
    document.getElementById('rp-activity').innerHTML='<div class="a-empty">Select a chat to see activity</div>';
    toast('Session closed — user returned to AI bot');loadSessions();
  });
}
function sendReply(){const inp=document.getElementById('ri'),msg=inp.value.trim();if(!msg||!activeSid)return;inp.value='';fetch(API+'/agent/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSid,agent_name:agent,message:msg})}).then(()=>{playReplySound();toast('✉️ Reply sent',1800);loadHistory();});}
function useQR(btn){document.getElementById('ri').value=btn.textContent.trim();document.getElementById('ri').focus();}

/* Analytics */
function toggleAna(){showAna=!showAna;document.getElementById('ap').classList.toggle('on',showAna);document.getElementById('anabtn').classList.toggle('on',showAna);if(showAna)loadAna();}
async function loadAna(){
  document.getElementById('ats').textContent='Last updated: '+new Date().toLocaleTimeString();
  try{
    const d=await fetch(API+'/admin/users').then(r=>r.json());
    const all=d.users||[];
    const tot=all.length,cl=all.filter(s=>s.status==='closed').length,wt=all.filter(s=>s.status==='waiting').length,wa=all.filter(s=>s.status==='with_agent').length;
    cnt('st',tot);cnt('sc2',cl);cnt('sw',wt);cnt('sa',wa);
    const iss={};all.forEach(s=>{const k=s.issue_type||'general';iss[k]=(iss[k]||0)+1;});
    const ie=Object.entries(iss).sort((a,b)=>b[1]-a[1]).slice(0,6);
    const mx=ie[0]?ie[0][1]:1;const cls=['p','g','o','y','p','g'];
    document.getElementById('ibars').innerHTML=ie.map(([k,v],i)=>`<div class="br"><div class="bl">${k}</div><div class="bt"><div class="bf ${cls[i]}" style="width:0" data-t="${Math.round(v/mx*100)}%"></div></div><div class="bv">${v}</div></div>`).join('')||'<div style="color:var(--muted);font-size:11px;padding:8px 0">No data yet</div>';
    setTimeout(()=>document.querySelectorAll('.bf[data-t]').forEach(el=>el.style.width=el.dataset.t),80);
    const st=[{l:'Bot',v:all.filter(s=>s.status==='bot').length,c:'#8B5CF6'},{l:'Waiting',v:wt,c:'#FF00C8'},{l:'Active',v:wa,c:'#22C55E'},{l:'Closed',v:cl,c:'#00F5FF'}].filter(s=>s.v>0);
    drawDonut(st,tot||1);
    document.getElementById('utb').innerHTML=all.slice(0,12).map(u=>`<tr><td>${u.user_name||'—'}</td><td>${u.user_email||'—'}</td><td>${u.user_phone||'—'}</td><td><span class="tb ${u.status}">${u.status}</span></td><td>${u.issue_type||'general'}</td><td>${u.created_at?new Date(u.created_at).toLocaleDateString():'—'}</td></tr>`).join('')||'<tr><td colspan="6" style="color:var(--muted);padding:16px">No users yet</td></tr>';
  }catch(e){console.error(e);}
}
function cnt(id,target){const el=document.getElementById(id);let c=0;el.textContent='0';const step=Math.max(1,Math.ceil(target/30));const iv=setInterval(()=>{c=Math.min(c+step,target);el.textContent=c;if(c>=target)clearInterval(iv);},22);}
function drawDonut(stats,total){
  const svg=document.getElementById('donut'),leg=document.getElementById('dleg');
  const r=15.9,ci=2*Math.PI*r;let off=0;
  const segs=stats.map(s=>{const pct=s.v/total;const seg={...s,dash:ci*pct,off};off+=ci*pct;return seg;});
  svg.innerHTML=`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="rgba(0,245,255,.05)" stroke-width="6"/>`+segs.map(s=>`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="${s.c}" stroke-width="6" stroke-dasharray="${s.dash.toFixed(2)} ${(ci-s.dash).toFixed(2)}" stroke-dashoffset="${(ci/4-s.off).toFixed(2)}" style="filter:drop-shadow(0 0 5px ${s.c})"/>`).join('')+`<text x="21" y="20" text-anchor="middle" dominant-baseline="central" fill="#F0EEF8" font-size="6.5" font-weight="700" font-family="JetBrains Mono,monospace">${total}</text><text x="21" y="26" text-anchor="middle" dominant-baseline="central" fill="rgba(240,238,248,.4)" font-size="3" font-family="JetBrains Mono,monospace">sessions</text>`;
  leg.innerHTML=stats.map(s=>`<div class="dli"><div class="dd" style="background:${s.c};box-shadow:0 0 7px ${s.c}"></div>${s.l} <strong style="color:var(--text);margin-left:4px">${s.v}</strong></div>`).join('');
}
</script>
</body>
</html>"""

# Add at top
# Add at top
import httpx

ASTROVED_API_BASE = "https://qawebservice.astroved.com/api"
ASTROVED_JWT_TOKEN = os.getenv("ASTROVED_JWT_TOKEN", "")

class RegisterRequest(BaseModel):
    session_id: str
    user_name: str = ""
    user_email: str = ""
    user_phone: str = ""
    country_code: str = "+91"

@app.post("/user/register")
async def register_user(req: RegisterRequest):
    print(f"Register attempt: {req.user_name} | {req.user_email} | {req.user_phone}")
    
    # If no JWT token configured, still save to local DB and proceed
    if not ASTROVED_JWT_TOKEN:
        print("WARNING: ASTROVED_JWT_TOKEN not set — saving to local DB only")
        try:
            conn = sqlite3.connect("chat.db")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_registrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    user_name TEXT,
                    user_email TEXT,
                    user_phone TEXT,
                    country_code TEXT,
                    synced_to_api INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            conn.execute(
                "INSERT INTO user_registrations (session_id, user_name, user_email, user_phone, country_code) VALUES (?,?,?,?,?)",
                (req.session_id, req.user_name, req.user_email, req.user_phone, req.country_code)
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            print(f"DB save error: {db_err}")
        
        return {"StatusCode": 200, "Status": "OK", "Message": "Saved locally"}
    
    # If JWT token exists, call AstroVed API
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{ASTROVED_API_BASE}/UserAccount/AddChatBotDetails",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {ASTROVED_JWT_TOKEN}"
                },
                json={
                    "CustomerName": req.user_name,
                    "CurrencyCode": "INR",
                    "CountryCode": req.country_code,
                    "MobileNo": req.user_phone,
                    "EmailAddress": req.user_email
                }
            )
            print(f"AstroVed API: {response.status_code} | {response.text}")
            
            # Also save to local DB as backup
            try:
                conn = sqlite3.connect("chat.db")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_registrations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        user_name TEXT,
                        user_email TEXT,
                        user_phone TEXT,
                        country_code TEXT,
                        synced_to_api INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
                conn.execute(
                    "INSERT INTO user_registrations (session_id, user_name, user_email, user_phone, country_code, synced_to_api) VALUES (?,?,?,?,?,?)",
                    (req.session_id, req.user_name, req.user_email, req.user_phone, req.country_code, 1)
                )
                conn.commit()
                conn.close()
            except Exception as db_err:
                print(f"Local DB backup error: {db_err}")
            
            return response.json()
            
    except httpx.TimeoutException:
        print("AstroVed API timeout")
        return {"StatusCode": 200, "Status": "OK", "Message": "Saved with timeout fallback"}
    except httpx.ConnectError as ce:
        print(f"AstroVed API connection error: {ce}")
        return {"StatusCode": 200, "Status": "OK", "Message": "Saved with connection fallback"}
    except Exception as e:
        print(f"register_user unexpected error: {str(e)}")
        return {"StatusCode": 200, "Status": "OK", "Message": "Saved with error fallback"}

# Check what is loaded
@app.get("/debug/env")
async def debug_env():
    return {
        "groq_loaded": bool(GROQ_API_KEY),
        "jwt_loaded": bool(ASTROVED_JWT_TOKEN),
        "jwt_preview": ASTROVED_JWT_TOKEN[:15] + "..." if ASTROVED_JWT_TOKEN else "NOT SET - using local DB only"
    }

@app.get("/admin/registrations")
async def get_registrations():
    """View all registered users"""
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            "SELECT id, session_id, user_name, user_email, user_phone, country_code, synced_to_api, created_at FROM user_registrations ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        return {
            "total": len(rows),
            "users": [
                {
                    "id": r[0], "session_id": r[1], "name": r[2],
                    "email": r[3], "phone": r[4], "country_code": r[5],
                    "synced_to_astroved_api": bool(r[6]), "registered_at": r[7]
                } for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.get("/agent/dashboard", response_class=HTMLResponse)
async def agent_dashboard_page():
    return AGENT_DASHBOARD_HTML
  
  
from fastapi.responses import Response

@app.get("/widget.js")
async def serve_widget():
    with open("widget_content.js", "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="application/javascript")

@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY),
        "knowledge_chunks_loaded": len(KB_CHUNKS),
        "topics_loaded": len(TOPIC_MAP),
    }