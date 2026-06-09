from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import sqlite3, os
from dotenv import load_dotenv

load_dotenv()

# ── Validate API key on startup ──────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

app = FastAPI()
client = Groq(api_key=GROQ_API_KEY)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://srivishnuu.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

CONFIDENTIAL EXCEPTION ONLY:
If payment/billing/refund/account details asked → say:
'Let me connect you with our specialist team.' and stop."""


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
    conn = sqlite3.connect("chat.db")
    rows = conn.execute(
        """SELECT role, content FROM messages 
           WHERE session_id=? 
           AND role IN ('user', 'assistant')
           ORDER BY created_at DESC LIMIT 20""",
        (session_id,)
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)
            if r in ("user", "assistant")]

def save_message(session_id: str, role: str, content: str):
    conn = sqlite3.connect("chat.db")
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()

init_db()

# ── Request model ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    message: str

# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        history = get_history(req.session_id)
        save_message(req.session_id, "user", req.message)

        # Build clean messages — only valid roles
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append(h)
        messages.append({"role": "user", "content": req.message})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        save_message(req.session_id, "assistant", reply)
        return {"reply": reply}

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY)
    }