"""Téléchargement, transcription, coupe des temps morts, recadrage 9:16 et sous-titres."""
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np

W, H, CAM_H = 1080, 1920, 608  # 608 = 1080 * 9/16 : facecam 16:9 en haut


# ---------- téléchargement ----------

def download(clip, rules, dest: Path):
    """Prend le passage dans la VOD avec du contexte autour du clip ; sinon le clip seul."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if clip["video_id"] and clip["vod_offset"] is not None:
        start = max(0, clip["vod_offset"] - rules["context_before"])
        end = clip["vod_offset"] + clip["duration"] + rules["context_after"]
        if end - start < rules["min_seconds"] + 2:  # marge pour les coupes
            start = max(0, end - rules["min_seconds"] - 2)
        try:
            _ytdlp(f"https://www.twitch.tv/videos/{clip['video_id']}", dest,
                   ["--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts"])
            return dest
        except subprocess.CalledProcessError:
            pass  # VOD supprimée ou réservée aux abonnés : on retombe sur le clip
    _ytdlp(clip["url"], dest, [])
    return dest


def _ytdlp(url, dest, extra):
    subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "best[height<=1080]/best",
                    "-o", str(dest), "--force-overwrites", *extra, url],
                   check=True, timeout=900)


# ---------- transcription ----------

_model = None


def transcribe(path, lang, model_name):
    """Renvoie (mots [(début, fin, texte)], audio mono 16 kHz)."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(model_name, device="cpu", compute_type="int8")
    # ffmpeg plutôt que faster_whisper.decode_audio : ce dernier casse avec PyAV >= 16
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=600).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    segments, _ = _model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True)
    words = [(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or []) if w.word.strip()]
    return words, audio


def rms(audio, hop=1600):
    n = len(audio) // hop
    return np.sqrt((audio[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else np.zeros(0)


def keep_intervals(words, energy, hop_s, duration, max_silence, pad=0.25):
    """Intervalles à garder : on coupe les blancs sans parole ET calmes plus longs que max_silence.
    Un blanc bruyant (explosion, cris non transcrits) est conservé : c'est souvent l'action."""
    if not words:
        return [(0.0, duration)]
    # Seuil relatif au niveau de la voix : un blanc est "mort" s'il est bien plus calme que la parole.
    voiced = np.concatenate([energy[int(s / hop_s): int(e / hop_s) + 1] for s, e, _ in words]) if len(energy) else []
    quiet = 0.3 * float(np.median(voiced)) if len(voiced) else 0.0

    def is_dead(a, b):
        seg = energy[int(a / hop_s): max(int(a / hop_s) + 1, int(b / hop_s))]
        return b - a > max_silence and (len(seg) == 0 or float(np.percentile(seg, 90)) < quiet)

    # Hook : on démarre juste avant le premier mot si le début est mort.
    start = max(0.0, words[0][0] - pad) if is_dead(0.0, words[0][0]) else 0.0
    cuts = []
    for (_, e1, _), (s2, _, _) in zip(words, words[1:]):
        if is_dead(e1, s2):
            cuts.append((e1 + pad, s2 - pad))
    end = min(duration, words[-1][1] + 1.0) if is_dead(words[-1][1], duration) else duration
    out, cur = [], start
    for a, b in cuts:
        out.append((cur, a))
        cur = b
    out.append((cur, end))
    return [(a, b) for a, b in out if b - a > 0.05]


def remap(t, intervals):
    """Temps d'origine -> temps dans la vidéo coupée (None si t tombe dans une coupe)."""
    acc = 0.0
    for a, b in intervals:
        if a <= t <= b:
            return acc + t - a
        acc += b - a
    return None


# ---------- sous-titres ASS ----------

def _ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(words, hook, credit, total, style):
    """Mots par groupes, mot actif surligné en jaune ; accroche en haut ; crédit en bas."""
    f, size = style["font"], style["font_size"]
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Word,{f},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1",
        f"Style: Hook,{f},64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,140,1",
        f"Style: Credit,{f},38,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,9,30,30,{CAM_H + 20},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if hook:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(min(total, 2.5))},Hook,,0,0,0,,{_esc(hook.upper())}")
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(total)},Credit,,0,0,0,,{_esc(credit)}")
    n = style["words_per_group"]
    y = CAM_H + 260  # juste sous la facecam, sur le jeu
    groups, cur = [], []
    for w in words:  # groupes de n mots, coupés en fin de phrase
        cur.append(w)
        if len(cur) == n or w[2][-1:] in ".?!":
            groups.append(cur)
            cur = []
    groups += [cur] if cur else []
    for group in groups:
        for i, (s, e, _) in enumerate(group):
            nxt = group[i + 1][0] if i + 1 < len(group) else e
            text = " ".join(("{\\c&H00FFFF&\\fscx112\\fscy112}" + _esc(w.upper()) + "{\\r}") if j == i
                            else _esc(w.upper()) for j, (_, _, w) in enumerate(group))
            lines.append(f"Dialogue: 0,{_ts(s)},{_ts(max(nxt, s + 0.05))},Word,,0,0,0,,{{\\pos({W // 2},{y})}}{text}")
    return "\n".join(lines) + "\n"


# ---------- facecam ----------

def detect_facecam(path, samples=8):
    """Cherche un visage IMMOBILE (même zone sur la majorité des images) = la facecam.
    Les visages du jeu bougent, ils ne passent pas le vote. Renvoie [x, y, w, h] en fractions ou None."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    hits, fw, fh = [], 1, 1
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        fh, fw = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for (x, y, w, h) in cascade.detectMultiScale(gray, 1.1, 6, minSize=(fh // 25, fh // 25)):
            hits.append((x, y, w, h))
    cap.release()
    return facecam_from_hits(hits, fw, fh, samples)


def facecam_from_hits(hits, fw, fh, samples):
    if not hits:
        return None
    cell = lambda x, y, w, h: (int((x + w / 2) / fw * 10), int((y + h / 2) / fh * 10))
    best, count = Counter(cell(*b) for b in hits).most_common(1)[0]
    if count < samples / 2:
        return None
    x, y, w, h = [int(np.median(v)) for v in zip(*[b for b in hits if cell(*b) == best])]
    cw = min(fw, w * 4.5)  # shortcut: cadre estimé depuis le visage ; régler "facecam" par streamer si mal cadré
    ch = min(fh, cw * 9 / 16)
    cx = min(max(0, x + w / 2 - cw / 2), fw - cw)
    cy = min(max(0, y + h / 2 - ch / 2), fh - ch)
    return [cx / fw, cy / fh, cw / fw, ch / fh]


# ---------- rendu ----------

def render(src, dst, intervals, ass_path, cam):
    sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in intervals)
    pre = (f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,fps=30[v0];"
           f"[0:a]aselect='{sel}',asetpts=N/SR/TB[a];")
    if cam:
        x, y, w, h = cam
        game_h = H - CAM_H
        layout = (f"[v0]split[c][g];"
                  f"[c]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"
                  f"scale={W}:{CAM_H}:force_original_aspect_ratio=increase,crop={W}:{CAM_H}[cam];"
                  f"[g]crop=ih*{W}/{game_h}:ih,scale={W}:{game_h}[game];"
                  f"[cam][game]vstack[v1];")
    else:
        layout = (f"[v0]split[b][f];"
                  f"[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20[bg];"
                  f"[f]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];")
    # Nom de fichier seul + cwd : un chemin complet casse le filtre ass (":" sous Windows, espaces...)
    graph = pre + layout + f"[v1]setsar=1,ass='{Path(ass_path).name}'[v]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(Path(src).resolve()), "-filter_complex", graph,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                    str(Path(dst).resolve())], check=True, timeout=1800, cwd=Path(ass_path).resolve().parent)
    return dst
