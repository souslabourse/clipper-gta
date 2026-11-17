"""Points d'entrée : python -m clipper tick|run|publish|recap|channels
tick = ce que GitHub Actions lance toutes les heures (commandes Telegram, publication, récupération, récap)."""
import json
import os
import secrets
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import buffer, edit, text, twitch
from .core import DATA, active_streamers, db, env, get_state, load_config, notify, set_state


def run(cfg, con):
    """Récupère les nouveaux clips puis en monte quelques-uns."""
    streamers = active_streamers(cfg, con)
    clips, missing = twitch.fetch_clips(cfg, streamers)
    if missing and missing != get_state(con, "missing"):
        notify(f"⚠️ Logins Twitch introuvables (à corriger dans config.yaml) : {', '.join(missing)}")
        set_state(con, "missing", missing)
    for c in clips:
        cols = ",".join(c)
        con.execute(f"INSERT OR IGNORE INTO clips ({cols}) VALUES ({','.join('?' * len(c))})", tuple(c.values()))
        con.execute("UPDATE clips SET views=?, score=? WHERE id=?", (c["views"], c["score"], c["id"]))
    con.commit()
    process(cfg, con, {s["login"]: s for s in streamers})
    cleanup(cfg, con)


def process(cfg, con, streamers):
    rules = cfg["rules"]
    rows = con.execute("SELECT * FROM clips WHERE status='new' ORDER BY score DESC LIMIT ?",
                       (cfg["fetch"]["process_per_run"],)).fetchall()
    for row in rows:
        clip = dict(row)
        if clip["login"] not in streamers:
            continue
        ready = con.execute("SELECT COUNT(*) FROM clips WHERE status='ready' AND lang=?", (clip["lang"],)).fetchone()[0]
        if ready >= cfg["fetch"]["max_ready_per_lang"]:
            continue  # stock suffisant : on garde l'hébergement léger et les clips frais
        raw = DATA / "raw" / f"{clip['id']}.mp4"
        try:
            edit.download(clip, rules, raw)
            words, audio = edit.transcribe(raw, clip["lang"], cfg["models"]["whisper"])
            iv = edit.keep_intervals(words, edit.rms(audio), 0.1, len(audio) / 16000, rules["max_silence"])
            iv = limit(iv, rules["max_seconds"])
            total = sum(b - a for a, b in iv)
            if total < rules["min_seconds"]:
                set_status(con, clip["id"], "skipped", error=f"trop court après coupe ({total:.0f}s)")
                continue
            meta = text.generate(clip, " ".join(w for _, _, w in words), clip["lang"], cfg["models"]["ollama"])
            moved = [(edit.remap(s, iv), edit.remap(e, iv), w) for s, e, w in words]
            moved = [(s, e, w) for s, e, w in moved if s is not None and e is not None]
            fc = streamers[clip["login"]].get("facecam", "auto")
            cam = None if fc == "none" else fc if isinstance(fc, list) else edit.detect_facecam(raw)
            out = DATA / "out" / f"{secrets.token_urlsafe(12)}.mp4"  # nom imprévisible : URL publique
            out.parent.mkdir(parents=True, exist_ok=True)
            ass = raw.with_suffix(".ass")
            ass.write_text(edit.build_ass(moved, meta["hook"], f"twitch.tv/{clip['login']}", total, cfg["style"]),
                           encoding="utf-8")
            edit.render(raw, out, iv, ass, cam)
            meta["seconds"] = round(total, 1)
            set_status(con, clip["id"], "ready", path=out.name, meta=json.dumps(meta, ensure_ascii=False))
        except Exception as e:  # un clip raté ne doit pas bloquer les autres
            set_status(con, clip["id"], "failed", error=str(e)[:500])
            print(traceback.format_exc(), file=sys.stderr)
        finally:
            for p in (raw, raw.with_suffix(".ass")):
                p.unlink(missing_ok=True)


def limit(intervals, max_s):
    out, acc = [], 0.0
    for a, b in intervals:
        if acc + (b - a) > max_s:
            out.append((a, a + max_s - acc))
            break
        out.append((a, b))
        acc += b - a
    return out


def set_status(con, cid, status, **kw):
    sets = ", ".join(["status=?"] + [f"{k}=?" for k in kw])
    con.execute(f"UPDATE clips SET {sets} WHERE id=?", (status, *kw.values(), cid))
    con.commit()


def cleanup(cfg, con):
    """Expire les clips trop vieux et supprime les vidéos publiées depuis plus de 24 h
    (Buffer les a déjà récupérées) : l'hébergement GitHub Pages reste sous 1 Go."""
    now = datetime.now(timezone.utc)
    oldest = (now - timedelta(hours=cfg["publish"]["max_clip_age_hours"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("UPDATE clips SET status='expired' WHERE status='ready' AND created_at < ?", (oldest,))
    for row in con.execute("SELECT id, status, path, posted_at FROM clips WHERE path IS NOT NULL").fetchall():
        posted_long_ago = row["posted_at"] and datetime.fromisoformat(row["posted_at"]) < now - timedelta(hours=24)
        if row["status"] in ("expired", "failed", "skipped") or posted_long_ago:
            (DATA / "out" / row["path"]).unlink(missing_ok=True)
            con.execute("UPDATE clips SET path=NULL WHERE id=?", (row["id"],))
    con.commit()


def due_slot(now, slots, window_min):
    """Créneau 'HH:MM' en cours (entre l'heure prévue et +window), sinon None."""
    for s in slots:
        h, m = map(int, s.split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if timedelta(0) <= now - start < timedelta(minutes=window_min):
            return s
    return None


def channels_for(lang):
    """CLIPPER_BUFFER_CHANNELS_FR="tiktok:abc,youtube:def" -> [('tiktok','abc'), ('youtube','def')]"""
    raw = os.environ.get(f"CLIPPER_BUFFER_CHANNELS_{lang.upper()}", "")
    return [tuple(x.split(":", 1)) for x in raw.split(",") if ":" in x]


def publish(cfg, con):
    if get_state(con, "paused", False):
        return
    pub = cfg["publish"]
    now = datetime.now(ZoneInfo(cfg["timezone"]))
    for lang, slots in pub["slots"].items():
        slot = due_slot(now, slots, pub["window_minutes"])
        if not slot or not os.environ.get(f"CLIPPER_BUFFER_KEY_{lang.upper()}"):
            continue  # pas de créneau, ou langue pas encore branchée sur Buffer
        key, day = f"{lang}:{now:%Y-%m-%d}:{slot}", f"{lang}:{now:%Y-%m-%d}:%"
        if con.execute("SELECT 1 FROM posts WHERE slot=?", (key,)).fetchone():
            continue
        if con.execute("SELECT COUNT(DISTINCT slot) FROM posts WHERE slot LIKE ?", (day,)).fetchone()[0] >= pub["max_per_day"]:
            continue
        oldest = (datetime.now(timezone.utc) - timedelta(hours=pub["max_clip_age_hours"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = con.execute("SELECT * FROM clips WHERE status='ready' AND lang=? AND created_at>=? "
                          "ORDER BY score DESC LIMIT 1", (lang, oldest)).fetchone()
        if not row:
            notify(f"ℹ️ Créneau {slot} ({lang}) : aucun clip prêt.")
            continue
        post_clip(cfg, con, row, lang, key, now)


def post_clip(cfg, con, row, lang, slot_key, now):
    meta = json.loads(row["meta"])
    url = f"{env('PUBLIC_BASE_URL').rstrip('/')}/{row['path']}"
    key_env = env(f"CLIPPER_BUFFER_KEY_{lang.upper()}")
    done = []
    for service, channel in channels_for(lang):
        try:
            bid = buffer.post(key_env, channel, service, url, meta, cfg["publish"]["youtube_category"])
            con.execute("INSERT INTO posts VALUES (?,?,?,?,?)", (row["id"], service, bid, slot_key, now.isoformat()))
            done.append(service)
        except Exception as e:
            notify(f"❌ Publication {service} ({lang}) échouée : {e}")
    if done:
        set_status(con, row["id"], "posted", posted_at=now.isoformat())
        notify(f"✅ Publié ({lang}, {', '.join(done)}) : {meta['title']} — {meta['seconds']}s, "
               f"{row['views']} vues Twitch\n{row['url']}")
    con.commit()


def test(cfg, con):
    """Test manuel en 2 lancements : 1) prépare un clip (7 derniers jours) ; 2) le publie tout de suite.
    Deux lancements car la vidéo doit être en ligne sur GitHub Pages avant que Buffer la télécharge."""
    poll_commands(cfg, con)
    langs = [lang for lang in cfg["publish"]["slots"] if os.environ.get(f"CLIPPER_BUFFER_KEY_{lang.upper()}")]
    if not langs:
        return notify("🧪 Test : aucune langue branchée sur Buffer.")
    lang = langs[0]
    row = con.execute("SELECT * FROM clips WHERE status='ready' AND lang=? AND path IS NOT NULL "
                      "AND id IN (SELECT value FROM json_each(?)) ORDER BY score DESC LIMIT 1",
                      (lang, json.dumps(get_state(con, "test_ready", [])))).fetchone()
    if row:
        now = datetime.now(ZoneInfo(cfg["timezone"]))
        notify(f"🧪 Test : publication immédiate de « {json.loads(row['meta'])['title']} »")
        return post_clip(cfg, con, row, lang, f"test:{now:%Y-%m-%d %H:%M}", now)
    cfg["fetch"].update(lookback_hours=24 * 7, process_per_run=2)
    cfg["streamers"] = [s for s in cfg["streamers"] if s["lang"] == lang]
    before = {r[0] for r in con.execute("SELECT id FROM clips WHERE status='ready'")}
    run(cfg, con)
    new = [r[0] for r in con.execute("SELECT id FROM clips WHERE status='ready' AND lang=?", (lang,)) if r[0] not in before]
    set_state(con, "test_ready", new)
    notify(f"🧪 Test : {len(new)} clip(s) {lang} préparé(s). Relance le test dans 2 min pour publier."
           if new else f"🧪 Test : aucun clip {lang} exploitable trouvé sur 7 jours.")


def recap(cfg, con):
    today = datetime.now(ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d")
    posted = con.execute("SELECT c.login, c.lang, c.meta, c.url FROM clips c WHERE c.posted_at LIKE ?",
                         (today + "%",)).fetchall()
    counts = dict(con.execute("SELECT status, COUNT(*) FROM clips GROUP BY status").fetchall())
    lines = [f"📊 Récap du {today}", f"Publiés aujourd'hui : {len(posted)}"]
    for p in posted:
        lines.append(f"• [{p['lang']}] {json.loads(p['meta'])['title']} — {p['url']}")
    lines.append("Stock : " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if get_state(con, "paused", False):
        lines.append("⏸️ Le système est EN PAUSE (/resume pour relancer).")
    progs = [s for s in cfg["streamers"] if s.get("program")]
    if posted and progs:
        lines.append("Pense à soumettre les clips des streamers à programme sur leur plateforme de campagne.")
    notify("\n".join(lines))


HELP = ("/status — état\n/pause — stoppe les publications\n/resume — relance\n"
        "/remove <login> — retire un streamer\n/restore <login> — le remet\n/list — streamers actifs")


def poll_commands(cfg, con):
    """Lit les messages Telegram reçus depuis le dernier passage. N'obéit qu'au chat configuré."""
    token, chat = os.environ.get("TELEGRAM_TOKEN"), str(os.environ.get("TELEGRAM_CHAT_ID"))
    if not token:
        return
    try:
        res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                           params={"offset": get_state(con, "tg_offset", 0), "timeout": 0}, timeout=30).json()
    except requests.RequestException:
        return
    for u in res.get("result", []):
        set_state(con, "tg_offset", u["update_id"] + 1)
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) == chat:  # sécurité : on ignore tout autre expéditeur
            notify(handle(cfg, con, msg.get("text", "")))


def tick(cfg, con):
    """Un passage horaire complet. Chaque étape est isolée : une panne n'empêche pas les autres."""
    steps = [("commandes", poll_commands), ("publication", publish), ("récupération", run)]
    now = datetime.now(ZoneInfo(cfg["timezone"]))
    if now.hour == 23 and get_state(con, "recap_day") != f"{now:%Y-%m-%d}":
        set_state(con, "recap_day", f"{now:%Y-%m-%d}")
        steps.append(("récap", recap))
    failed = False
    for name, fn in steps:
        try:
            fn(cfg, con)
        except Exception as e:
            failed = True
            notify(f"🔥 Panne ({name}) : {e}")
            print(traceback.format_exc(), file=sys.stderr)
    if failed:
        sys.exit(1)


def handle(cfg, con, text_in):
    parts = text_in.strip().split()
    cmd, arg = (parts[0].lower() if parts else ""), (parts[1].lower() if len(parts) > 1 else "")
    removed = get_state(con, "removed", [])
    if cmd == "/pause":
        set_state(con, "paused", True)
        return "⏸️ Publications en pause."
    if cmd == "/resume":
        set_state(con, "paused", False)
        return "▶️ Publications relancées."
    if cmd == "/remove" and arg:
        set_state(con, "removed", sorted(set(removed) | {arg}))
        return f"🚫 {arg} retiré."
    if cmd == "/restore" and arg:
        set_state(con, "removed", [r for r in removed if r != arg])
        return f"✅ {arg} remis."
    if cmd == "/list":
        return "Actifs : " + ", ".join(s["login"] for s in active_streamers(cfg, con))
    if cmd == "/status":
        counts = dict(con.execute("SELECT status, COUNT(*) FROM clips GROUP BY status").fetchall())
        return (("⏸️ EN PAUSE\n" if get_state(con, "paused", False) else "▶️ Actif\n")
                + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return HELP


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = load_config()
    if cmd == "channels":
        for lang in ("fr", "en"):
            if not os.environ.get(f"CLIPPER_BUFFER_KEY_{lang.upper()}"):
                continue
            for c in buffer.channels(os.environ[f"CLIPPER_BUFFER_KEY_{lang.upper()}"]):
                print(lang, c["service"], c["id"], c["name"])
        return
    fn = {"tick": tick, "test": test, "run": run, "publish": publish, "recap": recap}.get(cmd)
    if not fn:
        sys.exit("usage : python -m clipper tick|test|run|publish|recap|channels")
    con = db()
    try:
        fn(cfg, con)
    except Exception as e:
        notify(f"🔥 Panne ({cmd}) : {e}")
        raise


if __name__ == "__main__":
    main()
