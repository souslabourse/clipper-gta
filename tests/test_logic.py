"""Tests de la logique pure (sans ffmpeg, Twitch ni Buffer). Lancer : python -m pytest tests"""
from datetime import datetime

import numpy as np

from clipper import edit, text
from clipper.__main__ import channels_for, due_slot, handle, limit
from clipper.core import db, get_state


def test_coupe_les_blancs_calmes_mais_garde_les_blancs_bruyants():
    words = [(2.0, 2.5, "a"), (2.6, 3.0, "b"), (6.0, 6.5, "c"), (10.0, 10.4, "d")]
    energy = np.full(120, 1.0)          # 12 s, hop 0.1
    energy[:19] = 0.01                  # début silencieux -> coupé (hook)
    energy[31:59] = 0.01                # blanc calme 3.0-6.0 -> coupé
    # 6.5-10.0 reste bruyant (action) -> gardé
    iv = edit.keep_intervals(words, energy, 0.1, 12.0, 0.8)
    assert iv[0][0] == 1.75                      # démarre juste avant le premier mot
    assert any(a <= 3.25 and b <= 3.3 for a, b in iv[:1])
    assert any(a <= 7.0 <= b and a <= 9.5 <= b for a, b in iv)   # passage bruyant conservé
    assert all(not (a < 4.5 < b) for a, b in iv)                 # milieu du blanc calme coupé


def test_sans_parole_on_garde_tout():
    assert edit.keep_intervals([], np.ones(10), 0.1, 30.0, 0.8) == [(0.0, 30.0)]


def test_remap_et_limit():
    iv = [(1.0, 3.0), (5.0, 8.0)]
    assert edit.remap(2.0, iv) == 1.0
    assert edit.remap(6.0, iv) == 3.0
    assert edit.remap(4.0, iv) is None
    assert limit([(0, 50), (60, 100)], 90) == [(0, 50), (60, 100)]
    assert limit([(0, 50), (60, 120)], 90) == [(0, 50), (60, 100)]


def test_facecam_vote():
    still = [(1600, 50, 120, 120)] * 6             # visage immobile en haut à droite
    moving = [(400, 500, 100, 100), (900, 300, 100, 100)]
    cam = edit.facecam_from_hits(still + moving, 1920, 1080, 8)
    assert cam and cam[0] > 0.6 and cam[1] < 0.2
    assert abs(cam[0] + cam[2] - 1.0) < 1e-6 or cam[0] + cam[2] <= 1.0
    assert edit.facecam_from_hits(moving, 1920, 1080, 8) is None   # que des visages du jeu
    assert edit.facecam_from_hits([(540, 330, 30, 30)] * 6, 1920, 1080, 8) is None  # perso immobile au centre


def test_facecam_cadre_reel():
    gx, gy = np.zeros((1080, 1919)), np.zeros((1079, 1920))
    gx[:257, 458] = 50   # bord droit de la cam (x=459)
    gy[257, :459] = 50   # bord bas (y=258) ; la cam touche le coin haut-gauche
    gx[60:160, 134] = 50  # contour du casque : trop court pour être un bord de cam
    cam = edit.facecam_from_hits([(155, 88, 57, 57)] * 6, 1920, 1080, 8, gx, gy)
    got = [round(v * d) for v, d in zip(cam, (1920, 1080, 1920, 1080))]
    assert all(abs(a - b) <= 1 for a, b in zip(got, [0, 0, 459, 258])), got
    gx[:] = gy[:] = 0     # aucun cadre : on retombe sur l'estimation depuis le visage
    assert edit.facecam_from_hits([(155, 88, 57, 57)] * 6, 1920, 1080, 8, gx, gy)[2] < 0.15


def test_creneaux():
    paris = datetime(2026, 11, 19, 18, 5)
    assert due_slot(paris, ["12:30", "18:00"], 20) == "18:00"
    assert due_slot(paris.replace(hour=18, minute=25), ["18:00"], 20) is None
    assert due_slot(paris.replace(hour=0, minute=40), ["00:30"], 20) == "00:30"


def test_textes_de_secours_et_hashtags():
    clip = {"login": "kaicenat", "title": "LMAO"}
    m = text.finalize({}, clip, "en")
    assert m["title"].startswith("kaicenat") and "twitch.tv/kaicenat" in m["description"]
    m = text.finalize({"title": "X", "hook": "Y", "hashtags": ["#GTA6", "funny", "a", "b", "c"]}, clip, "fr")
    assert m["hashtags"][:3] == ["gta6", "gtarpfr", "kaicenat"] and len(m["hashtags"]) == 5
    assert "Crédit" in m["description"]
    assert text.finalize({}, {**clip, "name": "KaiCenat"}, "en")["title"].startswith("KaiCenat")


def test_ass_mot_actif_et_echappement():
    ass = edit.build_ass([(0.0, 0.4, "salut"), (0.5, 0.9, "{mec}")], "accroche", "twitch.tv/x", 10.0,
                         {"font": "DejaVu Sans", "font_size": 88, "words_per_group": 3})
    assert ass.count("Style: Word") == 1 and "ACCROCHE" in ass
    assert "{\\c&H00FFFF&" in ass and "(MEC)" in ass and "{MEC}" not in ass


def test_channels_env(monkeypatch):
    monkeypatch.setenv("CLIPPER_BUFFER_CHANNELS_FR", "tiktok:abc,youtube:def")
    assert channels_for("fr") == [("tiktok", "abc"), ("youtube", "def")]


def test_cleanup_supprime_publies_anciens_et_expire(tmp_path, monkeypatch):
    from clipper.__main__ import cleanup
    monkeypatch.setattr("clipper.core.DATA", tmp_path)
    monkeypatch.setattr("clipper.__main__.DATA", tmp_path)
    con = db()
    (tmp_path / "out").mkdir()
    for name in ("old.mp4", "fresh.mp4", "stale.mp4"):
        (tmp_path / "out" / name).write_bytes(b"x")
    con.executemany("INSERT INTO clips (id, status, path, posted_at, created_at) VALUES (?,?,?,?,?)", [
        ("a", "posted", "old.mp4", "2020-01-01T10:00:00+01:00", "2020-01-01T00:00:00Z"),
        ("b", "ready", "fresh.mp4", None, "2999-01-01T00:00:00Z"),
        ("c", "ready", "stale.mp4", None, "2020-01-01T00:00:00Z")])
    cleanup({"publish": {"max_clip_age_hours": 48}}, con)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["fresh.mp4"]
    assert con.execute("SELECT status FROM clips WHERE id='c'").fetchone()[0] == "expired"


def test_bot_pause_et_retrait(tmp_path, monkeypatch):
    monkeypatch.setattr("clipper.core.DATA", tmp_path)
    con = db()
    cfg = {"streamers": [{"login": "xqc"}, {"login": "lacy"}]}
    handle(cfg, con, "/pause")
    assert get_state(con, "paused") is True
    handle(cfg, con, "/remove XQC")
    assert "xqc" not in handle(cfg, con, "/list")
    handle(cfg, con, "/restore xqc")
    assert "xqc" in handle(cfg, con, "/list")


def test_voix_du_streamer_en_gros():
    turns = [(0.0, 5.0, 0), (5.0, 7.0, 1), (7.0, 12.0, 0)]  # voix 0 parle le plus = streamer
    words = [(1.0, 1.5, "salut"), (5.5, 6.0, "yo"), (8.0, 8.5, "mec"), (20.0, 20.5, "hors")]
    assert edit.words_owner(words, turns) == [True, False, True, True]
    ass = edit.build_ass([(0.0, 0.4, "moi", True), (0.5, 0.9, "lui", False)], "", "c", 2.0,
                         {"font": "F", "font_size": 90, "words_per_group": 3})
    lines = ass.splitlines()
    assert "Style: Other,F,54," in ass
    assert ",Word," in next(l for l in lines if "MOI" in l) and ",Other," in next(l for l in lines if "LUI" in l)


def test_apostrophes_recollees():
    words = [(0.0, 0.1, "d"), (0.1, 0.5, "'enquête"), (0.6, 0.7, "l'"), (0.7, 0.9, "a"), (1.0, 1.2, "est"), (1.2, 1.3, "-ce")]
    assert [w for _, _, w in edit.join_elisions(words)] == ["d'enquête", "l'a", "est-ce"]
    assert edit.join_elisions(words)[0] == (0.0, 0.5, "d'enquête")


def test_decouverte_categorie(monkeypatch):
    from clipper import twitch
    def clip(i, b, lang, views):
        return {"id": i, "broadcaster_id": b, "broadcaster_name": b.upper(), "language": lang, "view_count": views,
                "title": "t", "created_at": "2026-11-18T10:00:00Z", "url": "u", "duration": 30}
    clips = [clip("a", "1", "en", 5000), clip("b", "1", "en", 4000), clip("c", "2", "fr", 300),
             clip("d", "3", "en", 900), clip("e", "4", "es", 9000), clip("f", "5", "en", 2000)]
    def fake(h, path, params):
        return clips if path == "clips" else [{"id": x, "login": f"user{x}"} for _, x in params]
    monkeypatch.setattr(twitch, "_get", fake)
    out = twitch.discover({}, {"g"}, "x", {"en": 1000, "fr": 200}, {"user5"}, 1)
    # 1 clip max par streamer, langue gardée, seuil par langue, streamer exclu ignoré
    assert [(c["id"], c["login"], c["lang"]) for c in out] == [("a", "user1", "en"), ("c", "user2", "fr")]
