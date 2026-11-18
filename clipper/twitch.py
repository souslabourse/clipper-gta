"""Récupération des clips les plus vus via l'API Twitch Helix."""
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


def fetch_clips(cfg, streamers):
    """Renvoie (clips, logins_introuvables). Chaque clip est un dict prêt pour la base."""
    h = _headers()
    games = {g["id"] for g in _get(h, "games", [("name", n) for n in cfg["games"]])}
    users = {u["login"]: u["id"] for u in _get(h, "users", [("login", s["login"]) for s in streamers])}
    missing = [s["login"] for s in streamers if s["login"] not in users]
    since = (datetime.now(timezone.utc) - timedelta(hours=cfg["fetch"]["lookback_hours"]))
    out = []
    for s in streamers:
        if s["login"] not in users:
            continue
        data = _get(h, "clips", {"broadcaster_id": users[s["login"]], "first": 50,
                                 "started_at": since.strftime("%Y-%m-%dT%H:%M:%SZ")})
        mini = s.get("min_views", cfg["fetch"]["min_views"])
        data = [c for c in data if c["game_id"] in games and c["view_count"] >= mini]
        data.sort(key=lambda c: c["view_count"], reverse=True)
        boost = cfg["rules"]["program_boost"] if s.get("program") else 1.0
        for c in data[:cfg["fetch"]["clips_per_streamer"]]:
            out.append({
                "id": c["id"], "login": s["login"], "name": c.get("broadcaster_name") or s["login"], "lang": s["lang"], "title": c["title"],
                "views": c["view_count"], "created_at": c["created_at"], "url": c["url"],
                "video_id": c.get("video_id") or None, "vod_offset": c.get("vod_offset"),
                "duration": c["duration"], "score": c["view_count"] * boost})
    return out, missing
