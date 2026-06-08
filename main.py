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
SYSTEM_PROMPT = """You are AstroVed AI, a Astrology assistant.

RESPONSE RULES:
- Max 200 characters per reply
- If user asks for types/categories/list → show numbered list first, wait for selection
- After selection → explain only that item, brief and crisp
- No long paragraphs ever
- Be warm, mystical, concise

TOPICS YOU HANDLE:
- Birth charts & analysis
- Planetary transits
- Love & compatibility  
- Career & finance guidance
- Daily/weekly/monthly horoscopes
- Gemstones & remedies
- Yantras, Mantras & Pujas

LIST FORMAT EXAMPLE:
User: "types of yantras"
You: "✨ Yantra types:
1. Sri Yantra
2. Kuber Yantra
3. Navagraha Yantra
4. Ganesh Yantra
5. Durga Yantra
Which interests you?"

CONFIDENTIAL RULE:
If asked about payment/billing/refund/account → say exactly:
'For this, let me connect you with our specialist team.' and stop."""
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
           ORDER BY created_at DESC LIMIT 10""",
        (session_id,)
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

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

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": req.message}
        ]

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=200,
            temperature=0.6,
        )

        reply = response.choices[0].message.content
        save_message(req.session_id, "Assistant", reply)
        return {"reply": reply}

    except Exception as e:
        # Print error in terminal for debugging
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat error: {str(e)}"
        )

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY)
    }