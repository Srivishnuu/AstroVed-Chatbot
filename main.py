from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from groq import Groq
import sqlite3, os, asyncio, httpx
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# ── Validate API key ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are AstroVed.AI, a Vedic astrology assistant for AstroVed website.

RULES:
- Answer ALL questions the user asks — no restrictions
- Keep replies short: max 3-4 lines
- If user asks types/list → show numbered list, wait for selection
- After selection → explain in 3-4 lines
- Be warm, mystical, helpful always
- Never refuse any question

TOPICS (but not limited to):
Birth charts, Transits, Compatibility, Career, Horoscopes,
Gemstones, Yantras, Pujas, Mantras, Remedies, Numerology,
Vastu, Palmistry, Tarot, Hindu festivals, Vedic rituals

STRICT FORMAT RULES:
- NEVER use markdown: no **, no ##, no *, no bullet points with *
- Plain text only
- Max 3-4 lines per reply
- Use numbered lists only when showing options
...

CONFIDENTIAL EXCEPTION ONLY:
If payment/billing/refund/account details asked → say:
'Let me connect you with our specialist team.' and stop."""

# ── Keep-alive (prevents Render free tier sleeping) ───────────────────────────
async def keep_alive():
    await asyncio.sleep(60)  # Wait 1 min after startup
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://astroved-chatbot.onrender.com/")
                print(f"Keep-alive ping ✅ status={r.status_code}")
        except Exception as e:
            print(f"Keep-alive failed (ok): {e}")
        await asyncio.sleep(600)  # Ping every 10 minutes

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(keep_alive())
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)
client = Groq(api_key=GROQ_API_KEY)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
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
    conn.commit()
    conn.close()

def get_history(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        rows = conn.execute(
            """SELECT role, content FROM messages
               WHERE session_id=?
               AND role IN ('user', 'assistant')
               ORDER BY created_at DESC LIMIT 20""",
            (session_id,)
        ).fetchall()
        conn.close()
        # Reverse to get chronological order + strict role filter
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

init_db()

# ── Request model ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    message: str

# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # Step 1: Get history BEFORE saving new message
        history = get_history(req.session_id)

        # Step 2: Save user message
        save_message(req.session_id, "user", req.message)

        # Step 3: Build messages — STRICTLY only valid roles
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Ensure alternating user/assistant pattern
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({
                    "role": h["role"],
                    "content": str(h["content"])
                })

        # Add current user message
        messages.append({
            "role": "user",
            "content": str(req.message)
        })

        # Debug log
        print(f"Sending {len(messages)} messages to Groq")

        # Step 4: Call Groq
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )

        reply = response.choices[0].message.content

        # Step 5: Save reply
        save_message(req.session_id, "assistant", reply)

        return {"reply": reply}

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat error: {str(e)}"
        )

# ── Clear session endpoint ────────────────────────────────────────────────────
@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    try:
        conn = sqlite3.connect("chat.db")
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY)
    }