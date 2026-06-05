from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import sqlite3, os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Allow your frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLite setup
def init_db():
    conn = sqlite3.connect("chat.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_history(session_id: str):
    conn = sqlite3.connect("chat.db")
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY created_at LIMIT 20",
        (session_id,)
    ).fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in rows]

def save_message(session_id, role, content):
    conn = sqlite3.connect("chat.db")
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()

class ChatRequest(BaseModel):
    session_id: str
    message: str

@app.post("/chat")
async def chat(req: ChatRequest):
    history = get_history(req.session_id)
    save_message(req.session_id, "user", req.message)

    messages = [
        {"role": "system", "content": "You are a helpful assistant on this website. Be concise and friendly."},
        *history,
        {"role": "user", "content": req.message}
    ]

    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=messages,
        max_tokens=500
    )

    reply = response.choices[0].message.content
    save_message(req.session_id, "assistant", reply)
    return {"reply": reply}

@app.get("/")
def root():
    return {"status": "ok"}