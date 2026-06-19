from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from groq import Groq
import os, asyncio, httpx, re, hashlib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB

load_dotenv()

# ── Validate API key ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env file!")

SITE = "https://www.astroved.com"

# ── MySQL connection pool (cloud-safe: pings + reconnects automatically) ───────
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_SSL = os.getenv("DB_SSL", "true").lower() == "true"  # most cloud MySQL (PlanetScale/Railway/AWS) need SSL

if not all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME]):
    raise RuntimeError("MySQL DB_HOST/DB_USER/DB_PASSWORD/DB_NAME not found in .env file!")

_pool_kwargs = dict(
    creator=pymysql,
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=True,
    maxconnections=10,
    blocking=True,
    ping=1,            # PooledDB: ping connection before use, reconnect if dead (important for cloud DBs)
)
if DB_SSL:
    # Most managed MySQL providers require SSL; empty dict enables it with default certs.
    _pool_kwargs["ssl"] = {"ssl": {}}

POOL = PooledDB(**_pool_kwargs)

def get_conn():
    """Get a pooled MySQL connection. Always close() it (returns to pool, doesn't actually disconnect)."""
    return POOL.connection()

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

# ── TOPIC MAP ───────────────────────────────────────────────────────────────
TOPIC_MAP = {
    "nadi": {
        "keywords": ["nadi", "nadi astrology", "nadi leaf", "palm leaf", "bhrigu nadi"],
        "label": "📜 Nadi Astrology",
        "url": f"{SITE}/nadi/nadi-astrology",
        "fallback": (
            "Nadi Astrology is an ancient Tamil palm-leaf prediction system where sages "
            "centuries ago are believed to have inscribed individual life readings on dried "
            "palm leaves, identified today by your thumb impression. It covers your past, "
            "present, and future — including career, relationships, health, and remedies. "
            "It's considered one of the most personalized forms of Vedic prediction."
        ),
    },
    "horoscope_match": {
        "keywords": ["compatibility", "kundali match", "kundli match", "horoscope matching", "marriage match", "gun milan"],
        "label": "💑 Check Compatibility",
        "url": f"{SITE}/astropedia/en/freetools/horoscope-matching",
        "fallback": (
            "Horoscope Matching (Kundali Matching) compares two birth charts across factors "
            "like the 36 Guna Milan points, Mangal Dosha, and planetary compatibility to "
            "assess marital harmony. It highlights strengths and potential friction areas "
            "between partners before marriage."
        ),
    },
    "birth_chart": {
        "keywords": ["birth chart", "kundli", "kundali", "janam patrika", "janam kundli", "natal chart"],
        "label": "📊 View Birth Chart",
        "url": f"{SITE}/astropedia/en/freetools/birth-chart",
        "fallback": (
            "Your Birth Chart (Kundli) is a snapshot of the exact planetary positions at "
            "your time, date, and place of birth, mapped across the 12 houses. It's the "
            "foundation Vedic astrologers use to read personality, career, relationships, "
            "and timing of major life events."
        ),
    },
    "horoscope": {
        "keywords": ["horoscope", "moon sign", "rashi", "daily horoscope", "weekly horoscope", "monthly horoscope"],
        "label": "🌙 View Horoscope",
        "url": f"{SITE}/horoscopes",
        "fallback": (
            "Your Horoscope is a daily, weekly, or monthly forecast based on your Moon sign "
            "(Rashi), reflecting how current planetary transits are likely to affect your "
            "mood, relationships, career, and health. It's a quick way to stay aligned with "
            "the sky's current energy."
        ),
    },
    "gemstone": {
        "keywords": ["gemstone", "ruby", "emerald", "sapphire", "pearl stone", "navratna"],
        "label": "💎 Explore Gemstones",
        "url": f"{SITE}/astropedia/en/freetools/gemstone",
        "fallback": (
            "Vedic Gemstones are prescribed based on your birth chart to strengthen a "
            "weak or beneficial planet's influence in your life. Each stone — like Ruby for "
            "the Sun or Emerald for Mercury — is chosen, weighted, and worn according to "
            "astrological rules, not just preference."
        ),
    },
    "yantra": {
        "keywords": ["yantra"],
        "label": "🔱 Explore Yantras",
        "url": f"{SITE}/remedies/yantra",
        "fallback": (
            "A Yantra is a sacred geometric diagram used in Vedic tradition to focus "
            "energy and invoke specific planetary or divine blessings. Different Yantras "
            "are recommended for wealth, protection, health, or removing specific doshas, "
            "depending on your chart."
        ),
    },
    "puja": {
        "keywords": ["puja", "pooja", "ritual", "homa", "yagna", "havan"],
        "label": "🪔 View Pujas & Homas",
        "url": f"{SITE}/priest-services",
        "fallback": (
            "Pujas and Homas are traditional Vedic rituals performed by qualified priests "
            "to seek divine blessings, remove obstacles (doshas), and bring positive energy "
            "for specific life goals — from health and wealth to marriage and career. They "
            "can be performed on your behalf at sacred temples."
        ),
    },
    "numerology": {
        "keywords": ["numerology", "lucky number", "destiny number"],
        "label": "🔢 Numerology Reading",
        "url": f"{SITE}/astropedia/en/freetools/numerology",
        "fallback": (
            "Numerology studies the vibrational meaning of numbers derived from your birth "
            "date and name to reveal personality traits, life path, and lucky numbers. It's "
            "often used alongside astrology to fine-tune timing for major decisions."
        ),
    },
    "vastu": {
        "keywords": ["vastu"],
        "label": "🏠 Vastu Guidance",
        "url": f"{SITE}/astropedia/en/vastu",
        "fallback": (
            "Vastu Shastra is the ancient Indian science of architecture and space "
            "alignment, balancing the five elements within a home or workplace to promote "
            "health, prosperity, and harmony for those who live or work there."
        ),
    },
    "career": {
        "keywords": ["career", "business astrology", "job astrology", "profession"],
        "label": "💼 Career & Business",
        "url": f"{SITE}/career-money/career-money-astrology",
        "fallback": (
            "Career & Business Astrology examines the 10th house, its lord, and relevant "
            "planetary periods (dashas) in your chart to identify your ideal profession, "
            "favorable timing for job changes, and potential for business success."
        ),
    },
    "wealth": {
        "keywords": ["wealth", "finance astrology", "money astrology"],
        "label": "💰 Wealth & Finance",
        "url": f"{SITE}/wealth-finance/wealth-finance-astrology",
        "fallback": (
            "Wealth & Finance Astrology looks at the 2nd and 11th houses along with "
            "relevant planets to assess your financial strengths, potential risks, and the "
            "best periods for investment or major financial decisions."
        ),
    },
    "family": {
        "keywords": ["family astrology", "children astrology", "fertility"],
        "label": "👨‍👩‍👧 Family Astrology",
        "url": f"{SITE}/fertility-children/fertility-children-astrology",
        "fallback": (
            "Family & Fertility Astrology examines the 5th house and related planetary "
            "influences to offer guidance on childbirth timing, family harmony, and "
            "remedies for delays or obstacles in starting a family."
        ),
    },
    "education": {
        "keywords": ["education astrology", "study astrology", "exam astrology"],
        "label": "🎓 Education Astrology",
        "url": f"{SITE}/education-astrology",
        "fallback": (
            "Education Astrology studies the 4th and 5th houses to indicate academic "
            "strengths, the right field of study, and favorable timing for exams, "
            "admissions, or higher studies abroad."
        ),
    },
    "health": {
        "keywords": ["health astrology", "beauty astrology"],
        "label": "🩺 Health & Beauty",
        "url": f"{SITE}/beauty-health/beauty-health-astrology",
        "fallback": (
            "Health & Beauty Astrology looks at the 1st and 6th houses to highlight "
            "potential health vulnerabilities and suggest remedies, alongside guidance on "
            "planetary influences related to personal appearance and vitality."
        ),
    },
    "consult": {
        "keywords": ["consult", "talk to astrologer", "speak to astrologer", "book astrologer"],
        "label": "🔮 Talk to an Astrologer",
        "url": f"{SITE}/astrovedspeaks/",
        "fallback": (
            "AstroVed connects you directly with experienced Vedic astrologers for a live, "
            "personalized consultation — covering any area of your chart in depth, with "
            "follow-up questions answered in real time."
        ),
    },
    "remedies": {
        "keywords": ["remedy", "remedies", "dosha", "pariharam"],
        "label": "🌿 Explore Remedies",
        "url": f"{SITE}/dosha-pariharam/",
        "fallback": (
            "Vedic Remedies (Pariharams) are prescribed actions — rituals, gemstones, "
            "mantras, or charity — designed to ease the negative effects of doshas or "
            "weak planets identified in your birth chart, and strengthen beneficial ones."
        ),
    },
    "love": {
        "keywords": ["love", "relationship astrology", "marriage astrology"],
        "label": "❤️ Love & Relationships",
        "url": f"{SITE}/love-marriage/love-and-relationship",
        "fallback": (
            "Love & Relationship Astrology examines the 5th and 7th houses, Venus, and "
            "the Moon to offer insight into romantic compatibility, timing of marriage, and "
            "remedies for relationship challenges."
        ),
    },
    "store": {
        "keywords": ["store", "shop", "buy online"],
        "label": "🛒 Visit Store",
        "url": f"{SITE}/sale.aspx",
        "fallback": (
            "The AstroVed store offers astrology-recommended products — gemstones, "
            "yantras, rudraksha, and spiritual items — each selected to align with "
            "specific planetary remedies from your chart."
        ),
    },
}

def match_topic(user_text: str):
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
    if not KB_CHUNKS:
        return ""
    matches = [c for c in KB_CHUNKS if url_fragment in c["url"].lower()]
    if not matches:
        return ""
    result = ""
    for c in matches[:top_k]:
        result += f"\n[Page: {c['title']}]\nURL: {c['url']}\n{c['text'][:800]}\n"
    return result

BASE_SYSTEM_PROMPT = """You are AstroVed.AI, a Vedic astrology assistant for AstroVed website.

RULES:
- Answer using the WEBSITE CONTENT provided below when relevant to the question
- Keep replies short: max 3-4 lines
- If user asks types/list/categories -> show short numbered list, wait for selection
- After selection -> explain in 3-4 lines only
- Be warm, mystical, helpful always
- NEVER write out any URL or link in your reply text (no "https://", no "astroved.com/..."). 
  If a link is relevant, just say a link is available below — the app shows a button automatically. 
  Do NOT type, guess, or invent any link yourself, even if it looks plausible.
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

# ── MySQL schema setup — ALL tables ─────────────────────────────────────────────
def init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(64),
                role       VARCHAR(16),
                content    TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_session (session_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id    VARCHAR(64) PRIMARY KEY,
                user_name     VARCHAR(255),
                user_email    VARCHAR(255),
                user_phone    VARCHAR(64),
                status        VARCHAR(32) DEFAULT 'bot',
                assigned_agent VARCHAR(255),
                issue_type    VARCHAR(64),
                priority      VARCHAR(32) DEFAULT 'normal',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                username      VARCHAR(255) UNIQUE,
                password_hash VARCHAR(255),
                display_name  VARCHAR(255),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        conn.commit()
        cur.close()
    finally:
        conn.close()

def get_history(session_id: str):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT role, content FROM messages
               WHERE session_id=%s AND role IN ('user', 'assistant')
               ORDER BY created_at DESC LIMIT 20""",
            (session_id,)
        )
        rows = cur.fetchall()
        cur.close()
        history = []
        for r in reversed(rows):
            role, content = r["role"], r["content"]
            if role in ("user", "assistant") and content and str(content).strip():
                history.append({"role": role, "content": str(content).strip()})
        return history
    except Exception as e:
        print(f"get_history error: {e}")
        return []
    finally:
        conn.close()

def save_message(session_id: str, role: str, content: str):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (%s,%s,%s)",
            (session_id, role, content)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"save_message error: {e}")
    finally:
        conn.close()

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def seed_default_agents():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM agents")
        count = cur.fetchone()["c"]
        if count == 0:
            default_agents = [
                ("agent1", "astroved123", "Support Agent 1"),
                ("agent2", "astroved123", "Support Agent 2"),
            ]
            for username, pw, name in default_agents:
                cur.execute(
                    "INSERT INTO agents (username, password_hash, display_name) VALUES (%s,%s,%s)",
                    (username, hash_password(pw), name)
                )
            conn.commit()
            print("Seeded default agent accounts (CHANGE PASSWORDS IN PRODUCTION!)")
        cur.close()
    finally:
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

class SessionStartRequest(BaseModel):
    session_id: str
    user_name: str = ""
    user_email: str = ""
    user_phone: str = ""

@app.post("/session/start")
async def session_start(req: SessionStartRequest):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id FROM agent_sessions WHERE session_id=%s", (req.session_id,)
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """UPDATE agent_sessions
                   SET user_name=%s, user_email=%s, user_phone=%s
                   WHERE session_id=%s""",
                (req.user_name, req.user_email, req.user_phone, req.session_id)
            )
        else:
            cur.execute(
                """INSERT INTO agent_sessions
                   (session_id, user_name, user_email, user_phone, status)
                   VALUES (%s,%s,%s,%s, 'bot')""",
                (req.session_id, req.user_name, req.user_email, req.user_phone)
            )
        conn.commit()
        cur.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/admin/users")
async def admin_users():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT session_id, user_name, user_email, user_phone, status,
                      issue_type, created_at, updated_at
               FROM agent_sessions ORDER BY updated_at DESC"""
        )
        rows = cur.fetchall()
        cur.close()
        return {"users": rows}
    finally:
        conn.close()

# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM agent_sessions WHERE session_id=%s",
                (req.session_id,)
            )
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()

        if row and row["status"] == "with_agent":
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

        # ── Topic detection runs on the USER's message, not the bot's reply ──
        topic_key = match_topic(req.message)
        topic_info = TOPIC_MAP.get(topic_key) if topic_key else None

        system_content = BASE_SYSTEM_PROMPT

        if topic_info:
            url_fragment = topic_info["url"].replace(SITE, "").strip("/").split("/")[0]
            kb_content = search_knowledge_for_url(url_fragment)
            if not kb_content:
                kb_content = search_knowledge(req.message, top_k=2)
            if not kb_content:
                kb_content = f"[Page: {topic_info['label']}]\nURL: {topic_info['url']}\n{topic_info['fallback']}\n"

            system_content += TOPIC_FORCE_INSTRUCTION.format(
                label=topic_info["label"], content=kb_content
            )
        else:
            relevant_content = search_knowledge(req.message, top_k=3)
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

        return {
            "reply": reply,
            "mode": "bot",
            "topic_url": topic_info["url"] if topic_info else None,
            "topic_label": topic_info["label"] if topic_info else None,
        }

    except Exception as e:
        print(f"ERROR in /chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# ── Poll endpoint — frontend checks for agent replies ──────────────────────────
@app.get("/poll/{session_id}")
async def poll_session(session_id: str, since_id: int = 0):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, role, content FROM messages
               WHERE session_id=%s AND id > %s
               ORDER BY id ASC""",
            (session_id, since_id)
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT status, assigned_agent FROM agent_sessions WHERE session_id=%s",
            (session_id,)
        )
        status_row = cur.fetchone()
        cur.close()

        new_messages = [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]
        status = status_row["status"] if status_row else "bot"
        agent = status_row["assigned_agent"] if status_row else None

        return {"messages": new_messages, "status": status, "agent_name": agent}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Handoff endpoint ────────────────────────────────────────────────────────────
def create_or_update_handoff(session_id, name, email, phone, issue_type, priority):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id FROM agent_sessions WHERE session_id=%s", (session_id,)
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """UPDATE agent_sessions SET status='waiting', issue_type=%s, priority=%s
                   WHERE session_id=%s""",
                (issue_type, priority, session_id)
            )
        else:
            cur.execute(
                """INSERT INTO agent_sessions
                   (session_id, user_name, user_email, user_phone, status, issue_type, priority)
                   VALUES (%s,%s,%s,%s,'waiting',%s,%s)""",
                (session_id, name, email, phone, issue_type, priority)
            )
        conn.commit()
        cur.close()
    finally:
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
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT display_name, password_hash FROM agents WHERE username=%s",
            (req.username,)
        )
        row = cur.fetchone()
        cur.close()
        if not row or row["password_hash"] != hash_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return {"status": "ok", "display_name": row["display_name"], "username": req.username}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent: list sessions waiting / active ──────────────────────────────────────
@app.get("/agent/sessions")
async def agent_sessions():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT session_id, user_name, user_email, user_phone,
                      status, assigned_agent, issue_type, priority, updated_at
               FROM agent_sessions
               WHERE status IN ('waiting','with_agent')
               ORDER BY
                 CASE priority WHEN 'urgent' THEN 0 ELSE 1 END,
                 updated_at ASC"""
        )
        rows = cur.fetchall()
        cur.close()
        return {"sessions": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent: get full chat history for a session ─────────────────────────────────
@app.get("/agent/history/{session_id}")
async def agent_history(session_id: str):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, role, content, created_at AS time FROM messages WHERE session_id=%s ORDER BY id ASC",
            (session_id,)
        )
        rows = cur.fetchall()
        cur.close()
        return {"messages": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent: accept/claim a session ───────────────────────────────────────────────
@app.post("/agent/claim/{session_id}")
async def agent_claim(session_id: str, agent_name: str):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE agent_sessions SET status='with_agent', assigned_agent=%s WHERE session_id=%s",
            (agent_name, session_id)
        )
        conn.commit()
        cur.close()
        save_message(session_id, "system", f"{agent_name} has joined the chat")
        return {"status": "claimed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent: send reply ────────────────────────────────────────────────────────────
@app.post("/agent/reply")
async def agent_reply(req: AgentReplyRequest):
    conn = get_conn()
    try:
        save_message(req.session_id, "assistant", req.message)
        cur = conn.cursor()
        cur.execute(
            "UPDATE agent_sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=%s",
            (req.session_id,)
        )
        conn.commit()
        cur.close()
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent: close session (hand back to bot) ─────────────────────────────────────
@app.post("/agent/close")
async def agent_close(req: CloseSessionRequest):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE agent_sessions SET status='closed' WHERE session_id=%s",
            (req.session_id,)
        )
        conn.commit()
        cur.close()
        save_message(req.session_id, "system", "Agent has ended this conversation")
        return {"status": "closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ── Agent dashboard — live chat console for the CRM/support team ───────────────
AGENT_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AstroVed Support Console</title>
<style>
:root{--bg:#0A0818;--panel:#161330;--border:rgba(201,168,76,.25);--gold:#C9A84C;
--text:#EDE8D8;--muted:rgba(237,232,216,.55);--purple:#6C5CE7;--green:#22c55e;--red:#ef4444;}
*{box-sizing:border-box;margin:0;padding:0;font-family:Arial,'DM Sans',sans-serif}
body{background:var(--bg);color:var(--text);height:100vh;overflow:hidden}
#login{display:flex;align-items:center;justify-content:center;height:100vh}
.login-box{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:32px;width:320px}
.login-box h2{color:var(--gold);margin-bottom:18px;font-size:18px;text-align:center}
.login-box input{width:100%;padding:10px 12px;margin-bottom:12px;background:rgba(255,255,255,.06);
border:1px solid var(--border);border-radius:8px;color:var(--text);outline:none;font-size:14px}
.login-box button{width:100%;padding:10px;background:linear-gradient(135deg,var(--purple),var(--gold));
border:none;border-radius:8px;color:#fff;font-weight:600;cursor:pointer;font-size:14px}
#err{color:var(--red);font-size:12px;margin-top:8px;text-align:center;display:none}
#app{display:none;height:100vh}
#app.show{display:flex}
#sidebar{width:320px;border-right:1px solid var(--border);overflow-y:auto;background:var(--panel);flex-shrink:0}
#sidebar-hdr{padding:16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:var(--panel)}
#sidebar-hdr span{color:var(--gold);font-weight:600;font-size:14px}
#logout-btn{background:none;border:1px solid var(--border);color:var(--muted);border-radius:6px;padding:4px 10px;font-size:11px;cursor:pointer}
#sess-empty{padding:24px 16px;color:var(--muted);font-size:12px;text-align:center}
.sess-item{padding:12px 16px;border-bottom:1px solid rgba(255,255,255,.05);cursor:pointer;transition:background .15s}
.sess-item:hover{background:rgba(255,255,255,.04)}
.sess-item.active{background:rgba(108,92,231,.18)}
.sess-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;gap:8px}
.sess-name{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.badge{font-size:10px;padding:2px 7px;border-radius:10px;text-transform:uppercase;letter-spacing:.03em;flex-shrink:0}
.badge.waiting{background:rgba(239,68,68,.2);color:#fca5a5}
.badge.with_agent{background:rgba(34,197,94,.2);color:#86efac}
.sess-sub{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#chat-hdr{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
#chat-hdr h3{font-size:14px;color:var(--gold)}
#chat-hdr .sub{font-size:11px;color:var(--muted);margin-top:2px}
.hdr-btns button{margin-left:8px;padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:rgba(255,255,255,.05);color:var(--text);font-size:12px;cursor:pointer}
.hdr-btns button.claim{border-color:rgba(34,197,94,.5);color:#86efac}
.hdr-btns button.close{border-color:rgba(239,68,68,.5);color:#fca5a5}
#chat-body{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
.msg{max-width:70%;padding:9px 13px;border-radius:12px;font-size:13px;line-height:1.5;white-space:pre-wrap}
.msg.user{align-self:flex-start;background:rgba(255,255,255,.07)}
.msg.assistant{align-self:flex-end;background:linear-gradient(135deg,var(--purple),#4a3580)}
.msg.system{align-self:center;background:none;color:var(--muted);font-size:11px;font-style:italic;max-width:100%}
#reply-bar{padding:14px;border-top:1px solid var(--border);display:flex;gap:8px;flex-shrink:0}
#reply-input{flex:1;padding:10px 14px;border-radius:20px;border:1px solid var(--border);background:rgba(255,255,255,.06);color:var(--text);outline:none;font-size:13px}
#reply-send{padding:10px 20px;border-radius:20px;border:none;background:linear-gradient(135deg,var(--purple),var(--gold));color:#fff;font-weight:600;cursor:pointer}
#empty-state{flex:1;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px}
</style>
</head>
<body>

<div id="login">
  <div class="login-box">
    <h2>✦ AstroVed Support Console</h2>
    <input id="luser" placeholder="Username" autocomplete="username">
    <input id="lpass" type="password" placeholder="Password" autocomplete="current-password">
    <button onclick="doLogin()">Log In</button>
    <div id="err"></div>
  </div>
</div>

<div id="app">
  <div id="sidebar">
    <div id="sidebar-hdr">
      <span id="agent-name"></span>
      <button id="logout-btn" onclick="logout()">Log out</button>
    </div>
    <div id="sess-list"></div>
  </div>
  <div id="main">
    <div id="empty-state">Select a conversation from the left</div>
  </div>
</div>

<script>
const API = window.location.origin;
let agentName = '', activeSession = null, pollHist = null, pollList = null;

function doLogin() {
  const u = document.getElementById('luser').value.trim();
  const p = document.getElementById('lpass').value.trim();
  if (!u || !p) return;
  fetch(API + '/agent/login', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({username:u, password:p})
  }).then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(d => {
      agentName = d.display_name;
      sessionStorage.setItem('agentName', agentName);
      enterApp();
    })
    .catch(() => {
      document.getElementById('err').textContent = 'Invalid username or password';
      document.getElementById('err').style.display = 'block';
    });
}

function enterApp() {
  document.getElementById('login').style.display = 'none';
  document.getElementById('app').classList.add('show');
  document.getElementById('agent-name').textContent = '👤 ' + agentName;
  loadSessions();
  pollList = setInterval(loadSessions, 5000);
}

function logout() {
  sessionStorage.clear();
  clearInterval(pollList); clearInterval(pollHist);
  location.reload();
}

(function tryAutoLogin() {
  const saved = sessionStorage.getItem('agentName');
  if (saved) { agentName = saved; enterApp(); }
})();

function loadSessions() {
  fetch(API + '/agent/sessions').then(r => r.json()).then(d => {
    const list = document.getElementById('sess-list');
    if (!d.sessions.length) {
      list.innerHTML = '<div id="sess-empty">No chats waiting right now ✨</div>';
      return;
    }
    list.innerHTML = '';
    d.sessions.forEach(s => {
      const div = document.createElement('div');
      div.className = 'sess-item' + (s.session_id === activeSession ? ' active' : '');
      div.onclick = () => openSession(s.session_id, s.user_name, s.user_email, s.user_phone);
      const who = s.user_name || 'Anonymous visitor';
      const badgeTxt = s.status === 'waiting' ? 'Waiting' : (s.assigned_agent || 'Agent');
      div.innerHTML =
        '<div class="sess-top"><span class="sess-name">' + who + '</span>' +
        '<span class="badge ' + s.status + '">' + badgeTxt + '</span></div>' +
        '<div class="sess-sub">' + (s.user_email || s.user_phone || s.session_id.slice(0,16)) + ' · ' + (s.issue_type || 'general') + '</div>';
      list.appendChild(div);
    });
  }).catch(()=>{});
}

function openSession(sid, name, email, phone) {
  activeSession = sid;
  loadSessions();
  document.getElementById('main').innerHTML =
    '<div id="chat-hdr"><div><h3>' + (name || 'Anonymous visitor') + '</h3>' +
    '<div class="sub">' + (email || '') + (phone ? ' · ' + phone : '') + '</div></div>' +
    '<div class="hdr-btns">' +
    '<button class="claim" onclick="claimSession()">Claim chat</button>' +
    '<button class="close" onclick="closeSession()">End &amp; return to bot</button>' +
    '</div></div>' +
    '<div id="chat-body"></div>' +
    '<div id="reply-bar">' +
    '<input id="reply-input" placeholder="Type your reply…" onkeydown="if(event.key===\\'Enter\\')sendReply()">' +
    '<button id="reply-send" onclick="sendReply()">Send</button>' +
    '</div>';
  loadHistory();
  clearInterval(pollHist);
  pollHist = setInterval(loadHistory, 4000);
}

function loadHistory() {
  if (!activeSession) return;
  fetch(API + '/agent/history/' + activeSession).then(r => r.json()).then(d => {
    const body = document.getElementById('chat-body');
    if (!body) return;
    const wasAtBottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 30;
    body.innerHTML = d.messages.map(m =>
      '<div class="msg ' + m.role + '">' + (m.content || '').replace(/</g,'&lt;') + '</div>'
    ).join('');
    if (wasAtBottom) body.scrollTop = body.scrollHeight;
  }).catch(()=>{});
}

function claimSession() {
  if (!activeSession) return;
  fetch(API + '/agent/claim/' + activeSession + '?agent_name=' + encodeURIComponent(agentName), {method:'POST'})
    .then(() => { loadHistory(); loadSessions(); });
}

function closeSession() {
  if (!activeSession) return;
  fetch(API + '/agent/close', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: activeSession})
  }).then(() => {
    activeSession = null;
    clearInterval(pollHist);
    document.getElementById('main').innerHTML = '<div id="empty-state">Select a conversation from the left</div>';
    loadSessions();
  });
}

function sendReply() {
  const inp = document.getElementById('reply-input');
  const msg = inp.value.trim();
  if (!msg || !activeSession) return;
  inp.value = '';
  fetch(API + '/agent/reply', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: activeSession, agent_name: agentName, message: msg})
  }).then(loadHistory);
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
    db_ok = True
    try:
        conn = get_conn()
        conn.cursor().execute("SELECT 1")
        conn.close()
    except Exception:
        db_ok = False
    return {
        "status": "AstroVed.AI is online",
        "model": "llama-3.1-8b-instant",
        "api_key_loaded": bool(GROQ_API_KEY),
        "db_connected": db_ok,
        "db_host": DB_HOST,
        "knowledge_chunks_loaded": len(KB_CHUNKS),
        "topics_loaded": len(TOPIC_MAP),
    }