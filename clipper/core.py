"""Config, base SQLite, état (pause/retraits) et envoi Telegram."""
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CLIPPER_DATA", ROOT / "data"))


def env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Variable d'environnement manquante : {name}")
    return value


def load_config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def db():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "clipper.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY, login TEXT, lang TEXT, title TEXT, views INT,
            created_at TEXT, url TEXT, video_id TEXT, vod_offset INT, duration REAL,
            score REAL, status TEXT DEFAULT 'new', path TEXT, meta TEXT, error TEXT,
            posted_at TEXT, name TEXT);
        CREATE TABLE IF NOT EXISTS posts (
            clip_id TEXT, channel TEXT, buffer_id TEXT, slot TEXT, posted_at TEXT);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
    """)
    try:  # anciennes bases sans la colonne du nom affiché
        con.execute("ALTER TABLE clips ADD COLUMN name TEXT")
    except sqlite3.OperationalError:
        pass
    return con


def get_state(con, key, default=None):
    row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(con, key, value):
    con.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()


def active_streamers(cfg, con):
    removed = set(get_state(con, "removed", []))
    return [s for s in cfg["streamers"] if s["login"] not in removed]


def notify(text):
    """Message Telegram. Ne casse jamais le pipeline si Telegram est en panne."""
    print("[telegram]", text, flush=True)  # aussi dans les journaux GitHub, pour le diagnostic
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text[:4000]}, timeout=15)
    except requests.RequestException as e:
        print("[telegram] échec :", e)


def checkpoint(con):
    """Sauvegarde l'état sur la branche data tout de suite (GitHub Actions). Si la machine meurt ensuite,
    on sait ce qui a été publié et quel clip était en cours : pas de doublon, pas de boucle de pannes."""
    con.commit()
    if not (DATA / ".git").exists():
        return
    g = ["git", "-C", str(DATA), "-c", "user.name=clipper", "-c", "user.email=clipper@users.noreply.github.com"]
    subprocess.run(g + ["add", "-A"], check=True)
    if subprocess.run(g + ["commit", "-q", "--amend", "-m", "state"]).returncode:
        subprocess.run(g + ["commit", "-q", "-m", "state"])
    if subprocess.run(g + ["push", "-q", "-f", "origin", "HEAD:data"], timeout=300).returncode:
        print("checkpoint : push échoué", flush=True)
