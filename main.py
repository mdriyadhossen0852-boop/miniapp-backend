import hashlib, hmac, json, os, sqlite3
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BOT_TOKEN = os.environ["BOT_TOKEN"]
FRONTEND = "https://YOUR_FRONTEND_DOMAIN"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND],
    allow_methods=["*"],
    allow_headers=["*"],
)

def db():
    con = sqlite3.connect("app.db")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS videos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, thumb TEXT, category TEXT, url TEXT,
        likes INTEGER DEFAULT 0, downloads INTEGER DEFAULT 0,
        created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS likes(
        user_id INTEGER, video_id INTEGER,
        PRIMARY KEY(user_id, video_id));
    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER, user_name TEXT, text TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    con.commit()
    con.close()

init_db()

def verify(init_data: str) -> dict:
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received = data.pop("hash", None)
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(calc, received):
        raise HTTPException(401, "Invalid Telegram data")
    return json.loads(data["user"])

@app.get("/videos")
def list_videos(category: str = "", q: str = "", x_init_data: str = Header("")):
    verify(x_init_data)
    sql = "SELECT * FROM videos WHERE title LIKE ?"
    args = [f"%{q}%"]
    if category and category != "All":
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY id DESC LIMIT 50"
    con = db()
    rows = [dict(r) for r in con.execute(sql, args)]
    con.close()
    for r in rows:
        r.pop("url")
    return rows

@app.get("/videos/{vid}")
def get_video(vid: int, x_init_data: str = Header("")):
    user = verify(x_init_data)
    con = db()
    v = con.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not v:
        raise HTTPException(404, "Not found")
    v = dict(v)
    v.pop("url")
    v["liked"] = bool(con.execute(
        "SELECT 1 FROM likes WHERE user_id=? AND video_id=?",
        (user["id"], vid)).fetchone())
    v["comments"] = [dict(c) for c in con.execute(
        "SELECT user_name, text FROM comments WHERE video_id=? ORDER BY id DESC LIMIT 50",
        (vid,))]
    con.close()
    return v

@app.post("/videos/{vid}/like")
def like(vid: int, x_init_data: str = Header("")):
    user = verify(x_init_data)
    con = db()
    exists = con.execute(
        "SELECT 1 FROM likes WHERE user_id=? AND video_id=?",
        (user["id"], vid)).fetchone()
    if exists:
        con.execute("DELETE FROM likes WHERE user_id=? AND video_id=?", (user["id"], vid))
        con.execute("UPDATE videos SET likes = likes - 1 WHERE id=?", (vid,))
    else:
        con.execute("INSERT INTO likes VALUES(?,?)", (user["id"], vid))
        con.execute("UPDATE videos SET likes = likes + 1 WHERE id=?", (vid,))
    con.commit()
    n = con.execute("SELECT likes FROM videos WHERE id=?", (vid,)).fetchone()[0]
    con.close()
    return {"likes": n, "liked": not exists}

class Comment(BaseModel):
    text: str

@app.post("/videos/{vid}/comment")
def comment(vid: int, body: Comment, x_init_data: str = Header("")):
    user = verify(x_init_data)
    text = body.text.strip()[:300]
    if not text:
        raise HTTPException(400, "Empty")
    con = db()
    con.execute("INSERT INTO comments(video_id,user_name,text) VALUES(?,?,?)",
                (vid, user.get("first_name", "User"), text))
    con.commit()
    con.close()
    return {"ok": True}

@app.post("/videos/{vid}/download")
def download(vid: int, x_init_data: str = Header("")):
    verify(x_init_data)
    con = db()
    v = con.execute("SELECT url FROM videos WHERE id=?", (vid,)).fetchone()
    if not v:
        raise HTTPException(404, "Not found")
    con.execute("UPDATE videos SET downloads = downloads + 1 WHERE id=?", (vid,))
    con.commit()
    con.close()
    return {"url": v["url"]}
