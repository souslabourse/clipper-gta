"""Récupération des clips les plus vus via l'API Twitch Helix."""
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from .core import env

API = "https://api.twitch.tv/helix"


def _headers():
    r = requests.post("https://id.twitch.tv/oauth2/token", params={
        "client_id": env("TWITCH_CLIENT_ID"), "client_secret": env("TWITCH_CLIENT_SECRET"),
        "grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    return {"Client-Id": env("TWITCH_CLIENT_ID"), "Authorization": f"Bearer {r.json()['access_token']}"}


def _get(h, path, params):
    r = requests.get(f"{API}/{path}", headers=h, params=params, timeout=20)
    r.raise_for_status()
    return r.json()["data"]


def _clip(c, login, lang, boost=1.0):
    return {"id": c["id"], "login": login, "name": c.get("broadcaster_name") or login, "lang": lang,
            "title": c["title"], "views": c["view_count"], "created_at": c["created_at"], "url": c["url"],
            "video_id": c.get("video_id") or None, "vod_offset": c.get("vod_offset"),
            "duration": c["duration"], "score": c["view_count"] * boost}


def fetch_clips(cfg, streamers, removed=()):
    """Renvoie (clips, logins_introuvables). Chaque clip est un dict prêt pour la base."""
    h = _headers()
    games = {g["id"] for g in _get(h, "games", [("name", n) for n in cfg["games"]])}
    users = {u["login"]: u["id"] for u in _get(h, "users", [("login", s["login"]) for s in streamers])}
    missing = [s["login"] for s in streamers if s["login"] not in users]
    since = (datetime.now(timezone.utc) - timedelta(hours=cfg["fetch"]["lookback_hours"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    per = cfg["fetch"]["clips_per_streamer"]
    out = []
    for s in streamers:
        if s["login"] not in users:
            continue
        data = _get(h, "clips", {"broadcaster_id": users[s["login"]], "first": 50, "started_at": since})
        mini = s.get("min_views", cfg["fetch"]["min_views"])
        gta = [c for c in data if c["game_id"] in games]
        data = [c for c in gta if c["view_count"] >= mini]
        if s["lang"] == "fr" or data:  # journal : pourquoi un streamer ne donne rien
            print(f"{s['login']} : {len(gta)} clips GTA récents, {len(data)} ≥ {mini} vues, "
                  f"max {max((c['view_count'] for c in gta), default=0)} vues")
        data.sort(key=lambda c: c["view_count"], reverse=True)
        boost = cfg["rules"]["program_boost"] if s.get("program") else 1.0
        out += [_clip(c, s["login"], s["lang"], boost) for c in data[:per]]
    disc = cfg["fetch"].get("discover")  # {langue: vues mini} : meilleurs clips de toute la catégorie GTA
    if disc:
        out += discover(h, games, since, disc, {s["login"] for s in streamers} | set(removed), per)
    return out, missing


def discover(h, games, since, min_views, skip, per):
    """Clips les plus vus de la catégorie, tous streamers confondus (hors liste et hors /remove)."""
    found = [c for g in games for c in _get(h, "clips", {"game_id": g, "first": 100, "started_at": since})]
    found = [c for c in found if c.get("language") in min_views and c["view_count"] >= min_views[c["language"]]]
    ids = sorted({c["broadcaster_id"] for c in found})
    logins = {}
    for i in range(0, len(ids), 100):
        logins.update({u["id"]: u["login"] for u in _get(h, "users", [("id", x) for x in ids[i:i + 100]])})
    out, count = [], Counter()
    for c in sorted(found, key=lambda c: c["view_count"], reverse=True):
        login = logins.get(c["broadcaster_id"])
        if not login or login in skip or count[login] >= per:
            continue
        count[login] += 1
        out.append(_clip(c, login, c["language"]))
    print(f"découverte : {len(out)} clips de {len(count)} streamers ({', '.join(count)})")
    return out
