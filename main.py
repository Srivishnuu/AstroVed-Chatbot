from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import sqlite3, os, asyncio, httpx, re
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# ── Validate API key ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

# ── Load knowledge base into searchable chunks ────────────────────────────────
KB_CHUNKS = []  # list of {"title": ..., "url": ..., "text": ...}

def load_knowledge_base():
    """Parse knowledge_base.txt into per-page chunks for keyword search."""
    chunks = []
    try:
        with open("knowledge_base.txt", "r", encoding="utf-8") as f:
            content = f.read()

        # Split by page markers: "--- PAGE: Title (url) ---"
        parts = re.split(r"\n--- PAGE: (.*?) \((https?://[^\)]+)\) ---\n", content)
        # parts[0] is empty/junk before first marker
        # then triplets: title, url, text
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
    """Simple keyword-overlap search — finds most relevant page chunks."""
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

# ── System prompt (base, knowledge injected per-request) ──────────────────────
BASE_SYSTEM_PROMPT = """You are AstroVed.AI, a Vedic astrology assistant for AstroVed website.

RULES:
- Answer using the WEBSITE CONTENT provided below when relevant to the question
- Keep replies short: max 3-4 lines
- If user asks types/list/categories -> show short numbered list, wait for selection
- After selection -> explain in 3-4 lines only
- Be warm, mystical, helpful always
- If website content is provided and has a relevant product/page URL, mention you can share the link
- If no relevant website content given, answer using general Vedic astrology knowledge
- Never refuse a question

CONFIDENTIAL EXCEPTION:
If payment/billing/refund/account details asked -> say exactly:
'Let me connect you with our specialist team.' and stop."""

# ── Keep-alive (prevents Render free tier sleeping) ───────────────────────────
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

# ── App ───────────────────────────────────────────────────────────────────────
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
        history = get_history(req.session_id)
        save_message(req.session_id, "user", req.message)

        # Search knowledge base for relevant content based on this message
        relevant_content = search_knowledge(req.message, top_k=3)

        system_content = BASE_SYSTEM_PROMPT
        if relevant_content:
            system_content += f"\n\n=== RELEVANT WEBSITE CONTENT ===\n{relevant_content}\n=== END CONTENT ==="

        messages = [{"role": "system", "content": system_content}]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": str(req.message)})

        print(f"Sending {len(messages)} messages, KB context: {len(relevant_content)} chars")

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )

        reply = response.choices[0].message.content
        save_message(req.session_id, "assistant", reply)
        return {"reply": reply}

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

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
        "api_key_loaded": bool(GROQ_API_KEY),
        "knowledge_chunks_loaded": len(KB_CHUNKS)
    }