"""Apprentissage hebdo : relève les vues de nos TikTok (Apify) et ajuste la priorité de chaque streamer.
Sans APIFY_TOKEN, ne fait rien. Coût : ~0,30 $ par relevé (60 vidéos par compte)."""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import requests

from .core import get_state, notify, set_state

ACTOR = "https://api.apify.com/v2/acts/clockworks~tiktok-scraper/run-sync-get-dataset-items"


def fetch_videos(profiles, token):
    """[{title, views, posted}] des derniers TikTok de nos comptes."""
    r = requests.post(ACTOR, headers={"Authorization": f"Bearer {token}"}, timeout=600, json={
        "profiles": list(profiles), "resultsPerPage": 60, "profileScrapeSections": ["videos"],
        "shouldDownloadVideos": False, "shouldDownloadCovers": False})
    r.raise_for_status()
    return [{"title": (v.get("text") or "").split("\n")[0].strip(), "views": v.get("playCount") or 0,
             "posted": v.get("createTimeISO")} for v in r.json()]


def boosts_from(rows, min_posts=3, lo=0.3, hi=3.0):
    """rows = [(login, lang, vues)] -> {login: priorité}. Un streamer qui fait 2× la médiane de sa langue
    passe à ×2 ; il faut au moins `min_posts` vidéos pour juger (sinon « pas assez de données »)."""
    by_lang, by_login = defaultdict(list), defaultdict(list)
    for login, lang, views in rows:
        by_lang[lang].append(views)
        by_login[(login, lang)].append(views)
    out = {}
    for (login, lang), views in by_login.items():
        ref = median(by_lang[lang]) or 1
        if len(views) >= min_posts:
            out[login] = round(min(hi, max(lo, median(views) / ref)), 2)
    return out


def learn(cfg, con):
    token, profiles = os.environ.get("APIFY_TOKEN"), cfg["publish"].get("tiktok_profiles", {})
    if not token or not profiles:
        return
    videos = {v["title"].lower(): v for v in fetch_videos(profiles.values(), token)}
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows, slots = [], defaultdict(list)
    for login, lang, meta, posted_at in con.execute(
            "SELECT login, lang, meta, posted_at FROM clips WHERE status='posted' AND posted_at>=?", (since,)):
        v = videos.get(json.loads(meta)["title"].lower())
        if not v:
            continue
        rows.append((login, lang, v["views"]))
        hour = datetime.fromisoformat(posted_at).astimezone(ZoneInfo(cfg["timezone"])).strftime("%H:%M")
        slots[(lang, hour[:2] + "h")].append(v["views"])
    if not rows:
        return notify("📈 Apprentissage : aucune vidéo retrouvée sur TikTok (titres différents ?).")
    boosts = boosts_from(rows)
    set_state(con, "auto_boost", boosts)
    lines = [f"📈 Bilan TikTok (14 j, {len(rows)} vidéos retrouvées)"]
    for lang in sorted({r[1] for r in rows}):
        views = [r[2] for r in rows if r[1] == lang]
        lines.append(f"[{lang}] médiane {median(views):.0f} vues, meilleure {max(views)}")
    ranked = sorted(boosts.items(), key=lambda kv: kv[1], reverse=True)
    if ranked:
        lines.append("Priorité auto : " + ", ".join(f"{k} ×{v}" for k, v in ranked))
    best = sorted(((median(v), k) for k, v in slots.items() if len(v) >= 2), reverse=True)[:3]
    if best:
        lines.append("Meilleurs créneaux : " + ", ".join(f"{lang} {h} ({m:.0f} vues)" for m, (lang, h) in best))
    notify("\n".join(lines))


def due(con, now):
    """Le lundi, une fois par semaine."""
    week = now.strftime("%G-W%V")
    if now.weekday() == 0 and now.hour >= 10 and get_state(con, "learn_week") != week:
        set_state(con, "learn_week", week)
        return True
    return False
