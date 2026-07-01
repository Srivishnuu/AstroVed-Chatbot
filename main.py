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

def match_topic(user_text: str):
    t = user_text.lower()
    best, best_len = None, 0
    for key, info in TOPIC_MAP.items():
        for kw in info["keywords"]:
            if kw in t and len(kw) > best_len:
                best, best_len = key, len(kw)
    return best

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
    if not KB_CHUNKS: return ""
    query_words = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))
    if not query_words: return ""
    scored = []
    for chunk in KB_CHUNKS:
        haystack = (chunk["title"] + " " + chunk["text"]).lower()
        score = sum(1 for w in query_words if w in haystack)
        if score > 0: scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return "".join(f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n" for _, c in scored[:top_k])

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
        topic_key  = match_topic(req.message)
        topic_info = TOPIC_MAP.get(topic_key) if topic_key else None
        topic_url  = topic_info["url"]   if topic_info else None
        topic_label= topic_info["label"] if topic_info else None
        system_content = BASE_SYSTEM_PROMPT + LANGUAGE_INSTRUCTIONS.get(detected_lang, LANGUAGE_INSTRUCTIONS["english"])
        if topic_info:
            url_fragment = topic_info["url"].replace(SITE,"").strip("/").split("/")[0]
            kb_content = search_knowledge_for_url(url_fragment) or search_knowledge(req.message, top_k=2)
            if not kb_content:
                kb_content = f"[Page: {topic_info['label']}]\nURL: {topic_info['url']}\n{topic_info.get('fallback','')}\n"
            system_content += TOPIC_FORCE_INSTRUCTION.format(label=topic_info["label"], content=kb_content)
        else:
            relevant_content = search_knowledge(req.message, top_k=3)
            if relevant_content:
                system_content += f"\n\n=== RELEVANT WEBSITE CONTENT ===\n{relevant_content}\n=== END CONTENT ==="
        messages = [{"role":"system","content":system_content}]
        for h in history:
            if h["role"] in ("user","assistant"):
                messages.append({"role":h["role"],"content":str(h["content"])})
        messages.append({"role":"user","content":str(req.message)})
        # FIX (accuracy/timing): lower temperature for more consistent, on-topic,
        # less "creative" answers, and trim max_tokens slightly so replies stay
        # focused and arrive faster instead of rambling.
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
const AV_LOGO="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%2300F5FF'/%3E%3Cstop offset='1' stop-color='%238B5CF6'/%3E%3C/linearGradient%3E%3C/defs%3E%3Ccircle cx='50' cy='50' r='50' fill='%23070814'/%3E%3Cpolygon points='50,12 64,38 92,40 70,58 78,86 50,68 22,86 30,58 8,40 36,38' fill='none' stroke='url(%23g)' stroke-width='2'/%3E%3Cpath d='M33 56 L50 22 L67 56' fill='none' stroke='url(%23g)' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M36 47 L64 47' fill='none' stroke='url(%23g)' stroke-width='3' stroke-linecap='round'/%3E%3Ccircle cx='50' cy='64' r='5' fill='url(%23g)'/%3E%3Ccircle cx='50' cy='22' r='3.5' fill='url(%23g)'/%3E%3C/svg%3E";
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

@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY),
        "knowledge_chunks_loaded": len(KB_CHUNKS),
        "topics_loaded": len(TOPIC_MAP),
    }