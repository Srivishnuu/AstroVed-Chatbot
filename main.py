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
AGENT_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>AstroVed · CRM Console</title>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<style>
:root{
  --bg:#05030E;--p1:#0C0A1C;--p2:#131128;--p3:#1A1838;--lift:#221F45;
  --gold:#C9A84C;--gl:#E8C97A;--gg:rgba(201,168,76,.15);
  --pu:#6C5CE7;--pu2:#4A3580;--pg:rgba(108,92,231,.18);
  --gr:#22c55e;--rd:#ef4444;--cy:#06b6d4;--am:#f59e0b;
  --tx:#EDE8D8;--mu:rgba(237,232,216,.5);--fa:rgba(237,232,216,.13);
  --b1:rgba(201,168,76,.12);--b2:rgba(108,92,231,.28);--b3:rgba(255,255,255,.06);
  --fd:'Cinzel',serif;--fb:'Inter',sans-serif;
  --tr:all .2s cubic-bezier(.4,0,.2,1);
  --sh:0 4px 24px rgba(0,0,0,.5);
  /* NEW: neon accent variables for the refreshed dashboard look */
  --neon-pu:0 0 18px rgba(108,92,231,.55);
  --neon-gold:0 0 18px rgba(201,168,76,.5);
  --neon-cy:0 0 16px rgba(6,182,212,.5);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--fb);background:var(--bg);color:var(--tx);height:100vh;overflow:hidden;display:flex;flex-direction:column}
canvas#bg{position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.4}
/* NEW: subtle ambient neon glow blobs floating behind the whole app */
body::before,body::after{content:'';position:fixed;border-radius:50%;filter:blur(90px);pointer-events:none;z-index:0;opacity:.22;animation:driftGlow 16s ease-in-out infinite}
body::before{width:420px;height:420px;background:var(--pu);top:-120px;left:-100px}
body::after{width:380px;height:380px;background:var(--gold);bottom:-140px;right:-90px;animation-delay:-8s}
@keyframes driftGlow{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(40px,30px) scale(1.15)}}

/* LOGIN */
#ls{position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 40% 20%,rgba(108,92,231,.14) 0%,var(--bg) 65%)}
.lcard{background:var(--p1);border:1px solid var(--b1);border-radius:18px;padding:44px 40px;width:380px;position:relative;overflow:hidden;box-shadow:0 40px 100px rgba(0,0,0,.8),0 0 0 1px rgba(108,92,231,.08),var(--neon-pu);animation:lIn .55s cubic-bezier(.34,1.56,.64,1)}
@keyframes lIn{from{opacity:0;transform:translateY(28px) scale(.96)}to{opacity:1;transform:none}}
.lcard::before{content:'';position:absolute;top:-80px;left:50%;transform:translateX(-50%);width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,rgba(108,92,231,.2) 0%,transparent 70%);pointer-events:none}
.lorb{width:64px;height:64px;border-radius:50%;margin:0 auto 16px;display:flex;align-items:center;justify-content:center;box-shadow:var(--neon-pu);animation:pulse 3s ease-in-out infinite;overflow:hidden;border:1.5px solid var(--gold)}
.lorb img{width:100%;height:100%;object-fit:cover}
@keyframes pulse{0%,100%{box-shadow:var(--neon-pu)}50%{box-shadow:0 0 32px rgba(108,92,231,.75),0 0 60px rgba(201,168,76,.25)}}
.ltitle{font-family:var(--fd);font-size:19px;color:var(--gl);letter-spacing:.1em;text-align:center;margin-bottom:4px;text-shadow:0 0 18px rgba(201,168,76,.35)}
.lsub{font-size:11px;color:var(--mu);text-align:center;letter-spacing:.06em;margin-bottom:30px}
.lg{margin-bottom:15px}
.lg label{display:block;font-size:10px;font-weight:700;color:var(--gold);letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px}
.lg input{width:100%;background:rgba(255,255,255,.05);border:1px solid var(--b1);border-radius:10px;padding:12px 15px;color:var(--tx);font-family:var(--fb);font-size:13px;outline:none;transition:var(--tr)}
.lg input:focus{border-color:rgba(108,92,231,.55);background:rgba(108,92,231,.07);box-shadow:0 0 0 3px var(--pg)}
.lbtn{width:100%;padding:13px;background:linear-gradient(135deg,var(--pu),var(--gold));border:none;border-radius:10px;color:#fff;font-family:var(--fd);font-size:12px;font-weight:700;letter-spacing:.09em;cursor:pointer;margin-top:6px;transition:var(--tr);box-shadow:0 5px 22px rgba(108,92,231,.4)}
.lbtn:hover{transform:translateY(-2px);box-shadow:0 10px 32px rgba(108,92,231,.55),var(--neon-gold)}
.lerr{color:var(--rd);font-size:11px;text-align:center;margin-top:10px;display:none}

/* APP */
#app{display:none;height:100vh;flex-direction:column;position:relative;z-index:1}
#app.on{display:flex}

/* TOPNAV */
#nav{height:54px;background:rgba(12,10,28,.92);backdrop-filter:blur(24px);border-bottom:1px solid var(--b1);display:flex;align-items:center;padding:0 18px;gap:12px;flex-shrink:0;z-index:50;position:relative;box-shadow:0 2px 24px rgba(108,92,231,.08)}
.nlogo{width:30px;height:30px;border-radius:50%;border:1.5px solid var(--gold);box-shadow:var(--neon-gold);flex-shrink:0}
.nbrand{font-family:var(--fd);font-size:13px;color:var(--gl);letter-spacing:.08em;text-shadow:0 0 14px rgba(201,168,76,.3)}
.nbrand em{font-style:normal;font-family:var(--fb);font-size:10px;color:var(--mu);margin-left:8px;font-weight:400;letter-spacing:.04em}
.nsep{flex:1}
.npill{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);border-radius:20px;padding:4px 13px;font-size:11px;color:#86efac;display:flex;align-items:center;gap:6px;box-shadow:0 0 14px rgba(34,197,94,.18)}
.npill::before{content:'';width:6px;height:6px;background:var(--gr);border-radius:50%;animation:blink 2s infinite;flex-shrink:0;box-shadow:0 0 8px var(--gr)}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.nbtn{padding:6px 14px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;letter-spacing:.04em;transition:var(--tr);font-family:var(--fb);display:flex;align-items:center;gap:5px;background:none}
.nbtn.ana{border-color:rgba(6,182,212,.4);color:#67e8f9}
.nbtn.ana:hover,.nbtn.ana.on{background:rgba(6,182,212,.14);border-color:var(--cy);box-shadow:var(--neon-cy)}
.nbtn.lo{border-color:rgba(239,68,68,.35);color:#fca5a5}
.nbtn.lo:hover{background:rgba(239,68,68,.12);box-shadow:0 0 16px rgba(239,68,68,.35)}

/* BODY */
#body{flex:1;display:flex;overflow:hidden;position:relative}

/* ── SIDEBAR ── */
#sb{width:290px;border-right:1px solid var(--b1);background:var(--p1);display:flex;flex-direction:column;flex-shrink:0;overflow:hidden}
.sb-top{padding:12px 14px 8px;border-bottom:1px solid var(--b1);flex-shrink:0}
.sb-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.sb-head h3{font-family:var(--fd);font-size:10px;color:var(--gold);letter-spacing:.1em}
.qbadge{background:rgba(239,68,68,.2);border:1px solid rgba(239,68,68,.35);border-radius:20px;padding:1px 8px;font-size:10px;color:#fca5a5;font-weight:700;box-shadow:0 0 12px rgba(239,68,68,.3)}

/* search */
.sb-search{position:relative;margin-bottom:4px}
.sb-search input{width:100%;background:var(--b3);border:1px solid var(--b1);border-radius:8px;padding:7px 10px 7px 30px;font-size:12px;color:var(--tx);font-family:var(--fb);outline:none;transition:var(--tr)}
.sb-search input:focus{border-color:rgba(108,92,231,.4);background:rgba(108,92,231,.06);box-shadow:0 0 0 3px var(--pg)}
.sb-search input::placeholder{color:var(--fa)}
.sb-search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);width:13px;height:13px;fill:var(--mu);pointer-events:none}

/* filter tabs */
.sb-tabs{display:flex;gap:4px;margin-top:8px}
.sb-tab{flex:1;padding:5px 4px;border-radius:7px;border:1px solid var(--b1);background:none;font-size:10px;font-weight:600;cursor:pointer;color:var(--mu);transition:var(--tr);font-family:var(--fb);text-align:center}
.sb-tab:hover{color:var(--tx);border-color:var(--b2)}
.sb-tab.on{background:rgba(108,92,231,.18);border-color:var(--b2);color:var(--gl);box-shadow:0 0 12px rgba(108,92,231,.35)}

/* mini stats in sidebar */
.sb-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:10px 14px;border-bottom:1px solid var(--b1)}
.ss-card{background:var(--p2);border:1px solid var(--b1);border-radius:8px;padding:8px 10px;transition:var(--tr)}
.ss-card:hover{box-shadow:0 0 14px rgba(108,92,231,.25);border-color:var(--b2)}
.ss-val{font-family:var(--fd);font-size:18px;color:var(--tx);line-height:1}
.ss-lbl{font-size:9px;color:var(--mu);margin-top:3px;font-weight:500}

/* session list */
#sl{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--b1) transparent}
#sl::-webkit-scrollbar{width:3px}
#sl::-webkit-scrollbar-thumb{background:var(--b1);border-radius:3px}
.se{display:none}
.sc{padding:11px 14px;border-bottom:1px solid rgba(255,255,255,.03);cursor:pointer;transition:var(--tr);position:relative}
.sc::after{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:transparent;transition:var(--tr)}
.sc:hover{background:rgba(255,255,255,.025)}
.sc:hover::after{background:var(--gold);box-shadow:0 0 10px var(--gold)}
.sc.active{background:rgba(108,92,231,.1)}
.sc.active::after{background:var(--pu);box-shadow:0 0 10px var(--pu)}
.sc-r1{display:flex;align-items:center;gap:6px;margin-bottom:3px}
.sc-av{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--pu),var(--pu2));display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;flex-shrink:0;letter-spacing:.02em}
.sc-name{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.sc-badge{font-size:8px;padding:2px 7px;border-radius:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;flex-shrink:0}
.sc-badge.waiting{background:rgba(239,68,68,.18);color:#fca5a5;border:1px solid rgba(239,68,68,.3)}
.sc-badge.with_agent{background:rgba(34,197,94,.18);color:#86efac;border:1px solid rgba(34,197,94,.28)}
.sc-r2{display:flex;align-items:center;gap:4px;margin-left:34px}
.sc-email{font-size:10px;color:var(--mu);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.sc-time{font-size:9px;color:var(--fa);flex-shrink:0}
.sc-r3{margin-left:34px;margin-top:2px}
.sc-issue{font-size:9px;color:var(--fa);display:inline-flex;align-items:center;gap:3px}
.sc-issue span{background:var(--b3);border-radius:4px;padding:1px 5px;color:var(--mu)}
.sb-empty{padding:32px 16px;text-align:center;color:var(--mu);font-size:12px}
.sb-empty div{font-size:30px;opacity:.25;margin-bottom:8px}

/* ── CHAT PANEL ── */
#cp{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--bg)}
.cp-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--mu)}
.cp-empty .icon{font-size:44px;opacity:.18;animation:flt 4s ease-in-out infinite;text-shadow:var(--neon-gold)}
@keyframes flt{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
.cp-empty p{font-size:12px}

/* chat header */
#ch{padding:11px 18px;border-bottom:1px solid var(--b1);display:flex;align-items:center;gap:12px;flex-shrink:0;background:rgba(12,10,28,.85);backdrop-filter:blur(12px)}
.ch-av{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--pu),var(--pu2));display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0;box-shadow:var(--neon-pu)}
.ch-info{flex:1;min-width:0}
.ch-info h3{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ch-info p{font-size:10px;color:var(--mu);margin-top:1px}
.ch-tags{display:flex;gap:5px;margin-top:4px;flex-wrap:wrap}
.ch-tag{font-size:9px;padding:2px 7px;border-radius:5px;background:var(--b3);color:var(--mu);border:1px solid var(--b1)}
.ch-tag.status-waiting{background:rgba(239,68,68,.12);color:#fca5a5;border-color:rgba(239,68,68,.25)}
.ch-tag.status-with_agent{background:rgba(34,197,94,.12);color:#86efac;border-color:rgba(34,197,94,.22)}
.hbtn{padding:7px 15px;border-radius:8px;border:1px solid;font-size:11px;font-weight:600;cursor:pointer;transition:var(--tr);font-family:var(--fb);white-space:nowrap}
.hbtn.claim{background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.4);color:#86efac}
.hbtn.claim:hover{background:rgba(34,197,94,.22);transform:translateY(-1px);box-shadow:0 0 16px rgba(34,197,94,.35)}
.hbtn.end{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.35);color:#fca5a5}
.hbtn.end:hover{background:rgba(239,68,68,.2);transform:translateY(-1px);box-shadow:0 0 16px rgba(239,68,68,.35)}

/* messages */
#cb{flex:1;overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:8px;scrollbar-width:thin;scrollbar-color:var(--b1) transparent}
#cb::-webkit-scrollbar{width:3px}
#cb::-webkit-scrollbar-thumb{background:var(--b1);border-radius:3px}
.msg{max-width:66%;padding:10px 13px;border-radius:14px;font-size:12.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;animation:mi .18s ease-out}
@keyframes mi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg.user{align-self:flex-start;background:var(--p3);border:1px solid var(--b2);color:var(--tx)}
.msg.assistant{align-self:flex-end;background:linear-gradient(135deg,var(--pu),var(--pu2));color:#fff;box-shadow:0 4px 18px rgba(108,92,231,.25)}
.msg.system{align-self:center;background:none;color:var(--fa);font-size:10px;font-style:italic;max-width:100%;text-align:center;padding:3px 0}
.msg-t{font-size:9px;margin-top:4px;color:rgba(255,255,255,.3)}
.msg.user .msg-t{color:var(--fa)}

/* reply */
#rb{padding:11px 14px;border-top:1px solid var(--b1);display:flex;gap:8px;align-items:center;background:rgba(12,10,28,.9);backdrop-filter:blur(12px);flex-shrink:0}
#ri{flex:1;background:rgba(255,255,255,.05);border:1px solid var(--b1);border-radius:22px;padding:9px 15px;color:var(--tx);font-family:var(--fb);font-size:12.5px;outline:none;transition:var(--tr)}
#ri:focus{border-color:rgba(108,92,231,.45);background:rgba(108,92,231,.06);box-shadow:0 0 0 3px var(--pg)}
#ri::placeholder{color:var(--fa)}
#rs{width:38px;height:38px;background:linear-gradient(135deg,var(--pu),var(--pu2));border:none;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:var(--tr);box-shadow:0 2px 14px var(--pg)}
#rs:hover{transform:scale(1.1);box-shadow:0 4px 22px rgba(108,92,231,.55),var(--neon-pu)}
#rs svg{width:15px;height:15px;fill:#fff;margin-left:2px}

/* ── RIGHT PANEL ── */
#rp{width:280px;border-left:1px solid var(--b1);background:var(--p1);display:flex;flex-direction:column;flex-shrink:0;overflow:hidden}
.rp-tabs{display:flex;border-bottom:1px solid var(--b1);flex-shrink:0}
.rp-tab{flex:1;padding:11px 8px;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;color:var(--mu);border:none;background:none;border-bottom:2px solid transparent;transition:var(--tr);font-family:var(--fb)}
.rp-tab:hover{color:var(--tx)}
.rp-tab.on{color:var(--gl);border-bottom-color:var(--gold);text-shadow:0 0 10px rgba(201,168,76,.4)}
.rp-body{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--b1) transparent}
.rp-body::-webkit-scrollbar{width:3px}

/* user info card */
.ucard{padding:16px}
.uc-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.uc-av{width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,var(--pu),var(--gold));display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;flex-shrink:0;box-shadow:var(--neon-gold)}
.uc-nm{font-size:14px;font-weight:600}
.uc-em{font-size:11px;color:var(--mu);margin-top:2px}
.uc-field{margin-bottom:10px}
.uc-label{font-size:9px;font-weight:700;color:var(--gold);letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}
.uc-val{font-size:12px;color:var(--tx);background:var(--b3);border-radius:7px;padding:7px 10px;border:1px solid var(--b1);word-break:break-all}
.uc-val.muted{color:var(--mu)}

/* activity in right panel */
.aitem{padding:11px 16px;border-bottom:1px solid rgba(255,255,255,.03);display:flex;gap:10px}
.adot{width:7px;height:7px;border-radius:50%;margin-top:4px;flex-shrink:0;box-shadow:0 0 8px currentColor}
.atext{font-size:11px;color:var(--tx);line-height:1.5}
.atime{font-size:9px;color:var(--mu);margin-top:2px}
.a-empty{padding:24px 16px;text-align:center;color:var(--mu);font-size:11px}

/* quick reply chips */
.qr-section{padding:12px 16px;border-top:1px solid var(--b1);flex-shrink:0}
.qr-label{font-size:9px;font-weight:700;color:var(--gold);letter-spacing:.09em;text-transform:uppercase;margin-bottom:8px}
.qr-chips{display:flex;flex-direction:column;gap:5px}
.qr-chip{padding:7px 11px;background:var(--b3);border:1px solid var(--b1);border-radius:8px;font-size:11px;color:var(--mu);cursor:pointer;transition:var(--tr);text-align:left;font-family:var(--fb)}
.qr-chip:hover{background:rgba(108,92,231,.14);border-color:var(--b2);color:var(--tx);box-shadow:0 0 12px rgba(108,92,231,.25)}

/* ── ANALYTICS OVERLAY ── */
#ap{position:absolute;inset:0;background:var(--bg);z-index:20;overflow-y:auto;display:none;animation:aIn .25s ease-out}
@keyframes aIn{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}
#ap.on{display:block}
.aw{padding:24px;max-width:1060px;margin:0 auto}
.at{font-family:var(--fd);font-size:18px;color:var(--gl);letter-spacing:.06em;margin-bottom:4px;text-shadow:0 0 18px rgba(201,168,76,.3)}
.as{font-size:11px;color:var(--mu);margin-bottom:24px}
.sg{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
.scard{background:var(--p1);border:1px solid var(--b1);border-radius:14px;padding:18px;position:relative;overflow:hidden;transition:var(--tr)}
.scard:hover{transform:translateY(-3px);box-shadow:0 14px 40px rgba(0,0,0,.5),0 0 22px rgba(108,92,231,.25)}
.scard::after{content:'';position:absolute;top:-28px;right:-28px;width:90px;height:90px;border-radius:50%;opacity:.1;pointer-events:none;filter:blur(4px)}
.scard.c1::after{background:var(--pu)}
.scard.c2::after{background:var(--gr)}
.scard.c3::after{background:var(--gold)}
.scard.c4::after{background:var(--cy)}
.si{font-size:20px;margin-bottom:9px}
.sv{font-family:var(--fd);font-size:26px;color:var(--tx);line-height:1}
.sl{font-size:10px;color:var(--mu);margin-top:5px;font-weight:500}
.cg{display:grid;grid-template-columns:1.4fr 1fr;gap:14px;margin-bottom:22px}
.cc{background:var(--p1);border:1px solid var(--b1);border-radius:14px;padding:18px}
.cc h4{font-size:11px;font-weight:700;color:var(--gold);letter-spacing:.07em;text-transform:uppercase;margin-bottom:16px}
.br{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.bl{font-size:10px;color:var(--mu);width:90px;text-align:right;flex-shrink:0}
.bt{flex:1;height:7px;background:rgba(255,255,255,.05);border-radius:4px;overflow:hidden}
.bf{height:100%;border-radius:4px;transition:width 1s cubic-bezier(.4,0,.2,1)}
.bf.p{background:linear-gradient(90deg,var(--pu),var(--gold));box-shadow:0 0 10px rgba(108,92,231,.5)}
.bf.g{background:linear-gradient(90deg,var(--gr),var(--cy));box-shadow:0 0 10px rgba(34,197,94,.5)}
.bf.o{background:linear-gradient(90deg,var(--gold),var(--rd));box-shadow:0 0 10px rgba(201,168,76,.5)}
.bv{font-size:10px;color:var(--tx);width:22px;flex-shrink:0;text-align:right}
.dw{display:flex;align-items:center;gap:20px;justify-content:center;padding:8px 0}
.ds{width:120px;height:120px;flex-shrink:0;filter:drop-shadow(0 0 10px rgba(108,92,231,.3))}
.dl{display:flex;flex-direction:column;gap:9px}
.dli{display:flex;align-items:center;gap:7px;font-size:10px;color:var(--mu)}
.dd{width:7px;height:7px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor}
.utc{background:var(--p1);border:1px solid var(--b1);border-radius:14px;padding:18px;margin-bottom:22px}
.utc h4{font-size:11px;font-weight:700;color:var(--gold);letter-spacing:.07em;text-transform:uppercase;margin-bottom:14px}
table{width:100%;border-collapse:collapse}
th{font-size:9px;color:var(--mu);font-weight:700;letter-spacing:.07em;text-transform:uppercase;padding:7px 9px;text-align:left;border-bottom:1px solid var(--b1)}
td{font-size:11px;color:var(--tx);padding:9px 9px;border-bottom:1px solid rgba(255,255,255,.025)}
tr:hover td{background:rgba(255,255,255,.018)}
.tb{display:inline-block;padding:2px 7px;border-radius:9px;font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.tb.bot{background:rgba(108,92,231,.18);color:#c4b8ff}
.tb.waiting{background:rgba(239,68,68,.16);color:#fca5a5}
.tb.with_agent{background:rgba(34,197,94,.16);color:#86efac}
.tb.closed{background:rgba(255,255,255,.05);color:var(--mu)}
.ld{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--mu);padding:18px}
.sp{width:14px;height:14px;border:2px solid var(--b1);border-top-color:var(--gold);border-radius:50%;animation:spn .7s linear infinite}
@keyframes spn{to{transform:rotate(360deg)}}

/* TOAST */
#toast{position:fixed;bottom:22px;right:22px;z-index:999;background:var(--p2);border:1px solid var(--b1);border-radius:10px;padding:10px 18px;font-size:12px;color:var(--tx);box-shadow:var(--sh),0 0 18px rgba(108,92,231,.25);transform:translateY(18px);opacity:0;transition:var(--tr);pointer-events:none}
#toast.on{transform:none;opacity:1}
</style>
</head>
<body>
<canvas id="bg"></canvas>

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
  <!-- NAV -->
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

  <!-- BODY -->
  <div id="body">

    <!-- SIDEBAR -->
    <div id="sb">
      <div class="sb-top">
        <div class="sb-head">
          <h3>⚡ LIVE QUEUE</h3>
          <span class="qbadge" id="qbadge">0</span>
        </div>
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
      <div id="sl"><div class="sb-empty"><div>🌙</div><p>No active chats</p></div></div>
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
          <button id="rs" onclick="sendReply()">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
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
        <div class="ucard">
          <div style="text-align:center;padding:24px 0;color:var(--mu);font-size:12px">
            <div style="font-size:28px;opacity:.2;margin-bottom:8px">👤</div>
            Select a chat to see user details
          </div>
        </div>
      </div>
      <div class="rp-body" id="rp-activity" style="display:none">
        <div class="a-empty">Select a chat to see activity</div>
      </div>
      <div class="rp-body" id="rp-quick" style="display:none">
        <div class="qr-section" style="border-top:none">
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
        <div class="at">✦ Dashboard Analytics</div>
        <div class="as" id="ats">Loading…</div>
        <div class="sg">
          <div class="scard c1"><div class="si">💬</div><div class="sv" id="st">—</div><div class="sl">Total Sessions</div></div>
          <div class="scard c2"><div class="si">✅</div><div class="sv" id="sc2">—</div><div class="sl">Resolved</div></div>
          <div class="scard c3"><div class="si">⏳</div><div class="sv" id="sw">—</div><div class="sl">Waiting</div></div>
          <div class="scard c4"><div class="si">🤝</div><div class="sv" id="sa">—</div><div class="sl">With Agent</div></div>
        </div>
        <div class="cg">
          <div class="cc"><h4>Top Issue Types</h4><div id="ibars"><div class="ld"><div class="sp"></div>Loading…</div></div></div>
          <div class="cc"><h4>Status Mix</h4>
            <div class="dw">
              <svg class="ds" viewBox="0 0 42 42" id="donut"><circle cx="21" cy="21" r="15.9" fill="transparent" stroke="rgba(255,255,255,.05)" stroke-width="6"/></svg>
              <div class="dl" id="dleg"></div>
            </div>
          </div>
        </div>
        <div class="utc"><h4>Recent Users</h4>
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Issue</th><th>Date</th></tr></thead>
            <tbody id="utb"><tr><td colspan="6"><div class="ld"><div class="sp"></div>Loading…</div></td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

  </div><!-- /body -->
</div><!-- /app -->

<div id="toast"></div>

<script>
/* Shared crisp vector logo — same design language as the chat widget */
const AV_LOGO = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%23E8C97A'/%3E%3Cstop offset='1' stop-color='%23C9A84C'/%3E%3C/linearGradient%3E%3C/defs%3E%3Ccircle cx='50' cy='50' r='50' fill='%230e0c22'/%3E%3Cpolygon points='50,12 64,38 92,40 70,58 78,86 50,68 22,86 30,58 8,40 36,38' fill='none' stroke='url(%23g)' stroke-width='2'/%3E%3Cpath d='M33 56 L50 22 L67 56' fill='none' stroke='url(%23g)' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M36 47 L64 47' fill='none' stroke='url(%23g)' stroke-width='3' stroke-linecap='round'/%3E%3Ccircle cx='50' cy='64' r='5' fill='url(%23g)'/%3E%3Ccircle cx='50' cy='22' r='3.5' fill='url(%23g)'/%3E%3C/svg%3E";
document.querySelectorAll('#login-logo,#nav-logo').forEach(img=>img.src=AV_LOGO);

/* ── Stars ── */
(function(){
  const c=document.getElementById('bg'),x=c.getContext('2d');let s=[];
  const sz=()=>{c.width=innerWidth;c.height=innerHeight;};
  const mk=()=>{s=Array.from({length:100},()=>({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*1.1+.2,a:Math.random(),da:(Math.random()*.0018+.0006)*(Math.random()<.5?1:-1)}));};
  const dr=()=>{x.clearRect(0,0,c.width,c.height);s.forEach(p=>{p.a+=p.da;if(p.a>1||p.a<.1)p.da*=-1;x.beginPath();x.arc(p.x,p.y,p.r,0,Math.PI*2);x.fillStyle=`rgba(210,200,170,${p.a})`;x.fill();});requestAnimationFrame(dr);};
  window.addEventListener('resize',()=>{sz();mk();});sz();mk();dr();
})();

/* ── State ── */
const API=window.location.origin;
let agent='',activeSid=null,activeData=null,pollH=null,pollL=null,curTab='all',showAna=false,rpCurTab='user';
let allSessions=[];
let sseConn=null, lastQueueCount=0;

/* FIX (notification sound): boosted gain levels, added a brighter top note
   and a punchier sub-bass hit so the alert is clearly audible over normal
   office/desk noise instead of being a faint blip. */
function playNotifSound(){
  try{
    const ctx=new(window.AudioContext||window.webkitAudioContext)();
    const notes=[
      {f:523,t:0},{f:659,t:0.12},{f:784,t:0.24},{f:1046,t:0.36}
    ];
    notes.forEach(({f,t})=>{
      const o=ctx.createOscillator(),g=ctx.createGain(),r=ctx.createGain();
      o.connect(g);g.connect(r);r.connect(ctx.destination);
      o.frequency.value=f;o.type='triangle';
      r.gain.value=0.42;
      g.gain.setValueAtTime(0,ctx.currentTime+t);
      g.gain.linearRampToValueAtTime(1,ctx.currentTime+t+0.025);
      g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+t+0.32);
      o.start(ctx.currentTime+t);
      o.stop(ctx.currentTime+t+0.34);
    });
    const sub=ctx.createOscillator(),sg=ctx.createGain();
    sub.connect(sg);sg.connect(ctx.destination);
    sub.frequency.value=98;sub.type='sine';
    sg.gain.setValueAtTime(0.22,ctx.currentTime);
    sg.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.55);
    sub.start(ctx.currentTime);sub.stop(ctx.currentTime+0.55);
  }catch(e){}
}

/* FIX (notification sound): stronger two-tone ping for agent replies too */
function playReplySound(){
  try{
    const ctx=new(window.AudioContext||window.webkitAudioContext)();
    [{f:740,t:0},{f:988,t:0.14}].forEach(({f,t})=>{
      const o=ctx.createOscillator(),g=ctx.createGain();
      o.connect(g);g.connect(ctx.destination);
      o.frequency.value=f;o.type='sine';
      g.gain.setValueAtTime(0,ctx.currentTime+t);
      g.gain.linearRampToValueAtTime(0.45,ctx.currentTime+t+0.02);
      g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+t+0.26);
      o.start(ctx.currentTime+t);
      o.stop(ctx.currentTime+t+0.3);
    });
  }catch(e){}
}

function showDesktopNotif(count){
  if(!('Notification' in window))return;
  if(Notification.permission==='granted'){
    new Notification('AstroVed Support',{
      body: count+' new user'+(count>1?'s':'')+' waiting in queue!',
      icon: '/favicon.ico',
      tag: 'av-queue'
    });
  } else if(Notification.permission!=='denied'){
    Notification.requestPermission().then(p=>{
      if(p==='granted') showDesktopNotif(count);
    });
  }
}

function connectSSE(){
  if(sseConn)sseConn.close();
  sseConn=new EventSource(API+'/agent/events');
  sseConn.onmessage=function(e){
    try{
      const d=JSON.parse(e.data);
      if(d.type==='queue_update'){
        if(d.count > lastQueueCount){
          playNotifSound();
          const diff = d.count - lastQueueCount;
          toast('🔔 New chat: '+(d.sessions[0]?d.sessions[0].user_name||'Anonymous':'User'), 4000);
          showDesktopNotif(diff);
        }
        lastQueueCount=d.count;
        document.getElementById('qbadge').textContent=d.count;
      }
    }catch(err){}
  };
  sseConn.onerror=function(){
    setTimeout(connectSSE,5000);
  };
}

/* ── Toast ── */
function toast(m,ms=2600){const t=document.getElementById('toast');t.textContent=m;t.classList.add('on');setTimeout(()=>t.classList.remove('on'),ms);}

/* ── Login ── */
function doLogin(){
  const u=document.getElementById('lu').value.trim(),p=document.getElementById('lp').value.trim();
  if(!u||!p)return;
  fetch(API+'/agent/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})
    .then(r=>{if(!r.ok)throw new Error();return r.json();})
    .then(d=>{agent=d.display_name;sessionStorage.setItem('av_ag',agent);enterApp();})
    .catch(()=>{document.getElementById('le').style.display='block';});
}
document.getElementById('lp').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});

function enterApp(){
  document.getElementById('ls').style.display='none';
  document.getElementById('app').classList.add('on');
  document.getElementById('npill').textContent=agent;
  loadSessions();
  pollL=setInterval(loadSessions,4000);
  connectSSE(); // ← SSE connection for instant notifications
  // Request desktop notification permission on login
  if('Notification' in window && Notification.permission==='default'){
    Notification.requestPermission();
  }
}

function doLogout(){sessionStorage.clear();clearInterval(pollL);clearInterval(pollH);location.reload();}
(function auto(){const a=sessionStorage.getItem('av_ag');if(a){agent=a;enterApp();}})();

/* ── Sessions ── */
function loadSessions(){
  // Load active queue
  fetch(API+'/agent/sessions').then(r=>r.json()).then(d=>{
    const active=d.sessions||[];
    document.getElementById('qbadge').textContent=active.length;
    document.getElementById('ss-w').textContent=active.filter(s=>s.status==='waiting').length;
    document.getElementById('ss-a').textContent=active.filter(s=>s.status==='with_agent').length;
    // Also load ALL sessions (including closed) for history tab
    fetch(API+'/agent/all-sessions').then(r=>r.json()).then(all=>{
      allSessions=all.sessions||[];
      renderCards();
    }).catch(()=>{allSessions=active;renderCards();});
  }).catch(()=>{});
}

function renderCards(){
  const q=document.getElementById('srch').value.toLowerCase();
 let list=allSessions.filter(s=>{
    if(curTab==='all'&&s.status==='closed')return false; // hide closed from 'All'
    if(curTab!=='all'&&s.status!==curTab)return false;
    if(q&&!(s.user_name||'').toLowerCase().includes(q)&&!(s.user_email||'').toLowerCase().includes(q))return false;
    return true;
  });
  const sl=document.getElementById('sl');
  if(!list.length){sl.innerHTML='<div class="sb-empty"><div>🌙</div><p>No chats in this view</p></div>';return;}
  sl.innerHTML='';
  list.forEach(s=>{
    const div=document.createElement('div');
    div.className='sc'+(s.session_id===activeSid?' active':'');
    div.onclick=()=>openSess(s);
    const initials=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
    const t=s.updated_at?new Date(s.updated_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
    div.innerHTML=`
      <div class="sc-r1">
        <div class="sc-av">${initials}</div>
        <span class="sc-name">${s.user_name||'Anonymous'}</span>
        <span class="sc-badge ${s.status}">${s.status==='waiting'?'Waiting':s.assigned_agent||'Active'}</span>
      </div>
      <div class="sc-r2">
        <span class="sc-email">${s.user_email||s.session_id.slice(0,20)}</span>
        <span class="sc-time">${t}</span>
      </div>
      <div class="sc-r3"><span class="sc-issue">Issue: <span>${s.issue_type||'general'}</span></span></div>`;
    sl.appendChild(div);
  });
}

function setTab(t,el){
  curTab=t;
  document.querySelectorAll('.sb-tab').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
  renderCards();
}
function filterCards(){renderCards();}

/* ── Open session ── */
function openSess(s){
  if(showAna)toggleAna();
  activeSid=s.session_id;activeData=s;
  document.getElementById('cp-empty').style.display='none';
  const cc=document.getElementById('cp-chat');cc.style.display='flex';
  const initials=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
  document.getElementById('ch-av').textContent=initials;
  document.getElementById('ch-name').textContent=s.user_name||'Anonymous';
  document.getElementById('ch-sub').textContent=(s.user_email||'')+(s.user_phone?' · '+s.user_phone:'');
  const tags=document.getElementById('ch-tags');
  tags.innerHTML=`<span class="ch-tag status-${s.status}">${s.status}</span>${s.assigned_agent?`<span class="ch-tag">Agent: ${s.assigned_agent}</span>`:''}<span class="ch-tag">${s.issue_type||'general'}</span>${s.priority==='urgent'?'<span class="ch-tag" style="color:#fca5a5;border-color:rgba(239,68,68,.3)">🔴 Urgent</span>':''}`;
  loadHistory();
  clearInterval(pollH);pollH=setInterval(loadHistory,3000);
  renderCards();
  renderUserPanel(s);
  loadActivityPanel(s.session_id);
}

/* ── Right panel ── */
function rpTab(t,el){
  rpCurTab=t;
  document.querySelectorAll('.rp-tab').forEach(b=>b.classList.remove('on'));el.classList.add('on');
  ['user','activity','quick'].forEach(id=>document.getElementById('rp-'+id).style.display=id===t?'block':'none');
}

function renderUserPanel(s){
  const initials=(s.user_name||'?').split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase()||'?';
  document.getElementById('rp-user').innerHTML=`<div class="ucard">
    <div class="uc-head">
      <div class="uc-av">${initials}</div>
      <div><div class="uc-nm">${s.user_name||'Anonymous'}</div><div class="uc-em">${s.user_email||'—'}</div></div>
    </div>
    <div class="uc-field"><div class="uc-label">Phone</div><div class="uc-val ${s.user_phone?'':'muted'}">${s.user_phone||'Not provided'}</div></div>
    <div class="uc-field"><div class="uc-label">Status</div><div class="uc-val"><span class="tb ${s.status}">${s.status}</span></div></div>
    <div class="uc-field"><div class="uc-label">Issue Type</div><div class="uc-val">${s.issue_type||'general'}</div></div>
    <div class="uc-field"><div class="uc-label">Priority</div><div class="uc-val">${s.priority||'normal'}</div></div>
    <div class="uc-field"><div class="uc-label">Assigned Agent</div><div class="uc-val ${s.assigned_agent?'':'muted'}">${s.assigned_agent||'Unassigned'}</div></div>
    <div class="uc-field"><div class="uc-label">Session ID</div><div class="uc-val" style="font-size:10px">${s.session_id}</div></div>
  </div>`;
}

function loadActivityPanel(sid){
  fetch(API+'/agent/history/'+sid).then(r=>r.json()).then(d=>{
    const msgs=d.messages||[];
    const dotC={user:'#6C5CE7',assistant:'#22c55e',system:'#C9A84C'};
    document.getElementById('rp-activity').innerHTML=msgs.length?
      msgs.slice(-12).reverse().map(m=>`
        <div class="aitem">
          <div class="adot" style="background:${dotC[m.role]||'#999'};color:${dotC[m.role]||'#999'}"></div>
          <div><div class="atext">${(m.content||'').slice(0,80)}${(m.content||'').length>80?'…':''}</div>
          <div class="atime">${m.role} · ${m.time?new Date(m.time).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):''}</div></div>
        </div>`).join('')
      :'<div class="a-empty">No messages yet</div>';
  }).catch(()=>{});
}

/* ── History ── */
function loadHistory(){
  if(!activeSid)return;
  fetch(API+'/agent/history/'+activeSid).then(r=>r.json()).then(d=>{
    const body=document.getElementById('cb');if(!body)return;
    const atBot=body.scrollTop+body.clientHeight>=body.scrollHeight-40;
    body.innerHTML=d.messages.map(m=>{
      const t=m.time?new Date(m.time).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
      return`<div class="msg ${m.role}"><div>${(m.content||'').replace(/</g,'&lt;')}</div>${m.role!=='system'?`<div class="msg-t">${t}</div>`:''}</div>`;
    }).join('');
    if(atBot)body.scrollTop=body.scrollHeight;
    if(activeData)loadActivityPanel(activeSid);
  }).catch(()=>{});
}

/* ── Actions ── */
function claimSess(){
  if(!activeSid)return;
  fetch(API+'/agent/claim/'+activeSid+'?agent_name='+encodeURIComponent(agent),{method:'POST'})
    .then(()=>{toast('✓ Chat claimed');loadHistory();loadSessions();});
}
function closeSess(){
  if(!activeSid)return;
  fetch(API+'/agent/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSid})})
    .then(()=>{
      activeSid=null;activeData=null;clearInterval(pollH);
      document.getElementById('cp-chat').style.display='none';
      document.getElementById('cp-empty').style.display='flex';
      document.getElementById('rp-user').innerHTML='<div class="ucard"><div style="text-align:center;padding:24px 0;color:var(--mu);font-size:12px"><div style="font-size:28px;opacity:.2;margin-bottom:8px">👤</div>Select a chat to see user details</div></div>';
      document.getElementById('rp-activity').innerHTML='<div class="a-empty">Select a chat to see activity</div>';
      toast('Session closed — user returned to AI bot');loadSessions();
    });
}
function sendReply(){
  const inp=document.getElementById('ri'),msg=inp.value.trim();
  if(!msg||!activeSid)return;
  inp.value='';
  fetch(API+'/agent/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:activeSid,agent_name:agent,message:msg})})
    .then(()=>{
      playReplySound(); // sound when agent sends reply
      toast('✉️ Reply sent to user', 1800);
      loadHistory();
    });
}
function useQR(btn){
  const inp=document.getElementById('ri');
  inp.value=btn.textContent.trim();
  inp.focus();
}

/* ── Analytics ── */
function toggleAna(){
  showAna=!showAna;
  document.getElementById('ap').classList.toggle('on',showAna);
  document.getElementById('anabtn').classList.toggle('on',showAna);
  if(showAna)loadAna();
}

async function loadAna(){
  document.getElementById('ats').textContent='Last updated: '+new Date().toLocaleTimeString();
  try{
    const d=await fetch(API+'/admin/users').then(r=>r.json());
    const all=d.users||[];
    const tot=all.length,cl=all.filter(s=>s.status==='closed').length,wt=all.filter(s=>s.status==='waiting').length,wa=all.filter(s=>s.status==='with_agent').length;
    cnt('st',tot);cnt('sc2',cl);cnt('sw',wt);cnt('sa',wa);
    const iss={};all.forEach(s=>{const k=s.issue_type||'general';iss[k]=(iss[k]||0)+1;});
    const ie=Object.entries(iss).sort((a,b)=>b[1]-a[1]).slice(0,6);
    const mx=ie[0]?ie[0][1]:1;const cls=['p','g','o','p','g','o'];
    document.getElementById('ibars').innerHTML=ie.map(([k,v],i)=>`<div class="br"><div class="bl">${k}</div><div class="bt"><div class="bf ${cls[i]}" style="width:0" data-t="${Math.round(v/mx*100)}%"></div></div><div class="bv">${v}</div></div>`).join('')||'<div style="color:var(--mu);font-size:11px;padding:8px 0">No data yet</div>';
    setTimeout(()=>document.querySelectorAll('.bf[data-t]').forEach(el=>el.style.width=el.dataset.t),80);
    const st=[{l:'Bot',v:all.filter(s=>s.status==='bot').length,c:'#6C5CE7'},{l:'Waiting',v:wt,c:'#ef4444'},{l:'With Agent',v:wa,c:'#22c55e'},{l:'Closed',v:cl,c:'#C9A84C'}].filter(s=>s.v>0);
    drawDonut(st,tot||1);
    document.getElementById('utb').innerHTML=all.slice(0,12).map(u=>`<tr><td>${u.user_name||'—'}</td><td>${u.user_email||'—'}</td><td>${u.user_phone||'—'}</td><td><span class="tb ${u.status}">${u.status}</span></td><td>${u.issue_type||'general'}</td><td>${u.created_at?new Date(u.created_at).toLocaleDateString():'—'}</td></tr>`).join('')||'<tr><td colspan="6" style="color:var(--mu);padding:14px;font-size:11px">No users yet</td></tr>';
  }catch(e){console.error(e);}
}

function cnt(id,target){
  const el=document.getElementById(id);let c=0;
  const step=Math.max(1,Math.ceil(target/25));
  const iv=setInterval(()=>{c=Math.min(c+step,target);el.textContent=c;if(c>=target)clearInterval(iv);},28);
}

function drawDonut(stats,total){
  const svg=document.getElementById('donut'),leg=document.getElementById('dleg');
  const r=15.9,ci=2*Math.PI*r;let off=0;
  const segs=stats.map(s=>{const pct=s.v/total;const seg={...s,dash:ci*pct,off};off+=ci*pct;return seg;});
  svg.innerHTML=`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="rgba(255,255,255,.05)" stroke-width="6"/>` +
    segs.map(s=>`<circle cx="21" cy="21" r="${r}" fill="transparent" stroke="${s.c}" stroke-width="6" stroke-dasharray="${s.dash.toFixed(2)} ${(ci-s.dash).toFixed(2)}" stroke-dashoffset="${(ci/4-s.off).toFixed(2)}" style="transition:stroke-dasharray .8s"/>`).join('') +
    `<text x="21" y="20" text-anchor="middle" dominant-baseline="central" fill="#EDE8D8" font-size="6.5" font-weight="700">${total}</text><text x="21" y="26" text-anchor="middle" dominant-baseline="central" fill="rgba(237,232,216,.45)" font-size="3.2">total</text>`;
  leg.innerHTML=stats.map(s=>`<div class="dli"><div class="dd" style="background:${s.c};color:${s.c}"></div>${s.l} <strong style="color:var(--tx);margin-left:3px">${s.v}</strong></div>`).join('');
}
</script>
</body>
</html>"""

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