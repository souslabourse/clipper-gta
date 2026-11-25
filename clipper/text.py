"""Accroche, titre et hashtags : Claude Haiku si ANTHROPIC_API_KEY est défini (bien meilleur en français,
~0,3 $/mois), sinon Ollama en local (gratuit)."""
import json
import os
import re
import sys

import requests

PROMPT = {
    "fr": "Tu écris le titre TikTok d'un clip GTA 6, en français familier mais SANS faute d'orthographe.\n"
          "Streamer : {login}. Titre Twitch du clip : \"{title}\". Ce qui est dit : \"{transcript}\".\n"
          "Le titre raconte ce qui se passe dans CE clip, avec un détail concret tiré de ce qui est dit "
          "(un objet, un lieu, une personne, une phrase), et donne envie de voir la fin sans la dévoiler.\n"
          "Formes possibles (choisis celle qui colle, n'invente aucun détail) : une situation qui tourne mal, "
          "une citation choc entre « », une question au spectateur, « POV : ... ».\n"
          "Règles : une phrase complète avec un verbe, le nom {login} une seule fois, jamais « il » ou « elle » "
          "pour parler du streamer, 1 ou 2 emojis à la fin, 70 caractères max. "
          "Mots interdits : réaction, incroyable, épique, moment, dingue, truc, et pas de point d'exclamation.\n"
          "Titres déjà publiés (n'en reprends ni la forme ni les mots) : {recent}\n"
          "hook : 3 à 6 mots affichés en gros au début, une tension sans dévoiler la fin.\n"
          "question : une question courte aux spectateurs sur ce clip, pour qu'ils répondent en commentaire.\n"
          "tag : un seul hashtag sur le sujet du clip (sans #).\n"
          "Réponds uniquement en JSON : {{\"hook\": \"...\", \"title\": \"...\", \"question\": \"...\", \"tag\": \"...\"}}",
    "en": "You write the TikTok title of a GTA 6 clip in casual but correct US English.\n"
          "Streamer: {login}. Twitch clip title: \"{title}\". What is said: \"{transcript}\".\n"
          "The title tells what happens in THIS clip, with one concrete detail taken from what is said "
          "(an object, a place, a person, a line), and makes people want to see the ending without spoiling it.\n"
          "Possible shapes (pick the one that fits, never invent details): a situation going wrong, "
          "a shocking quote in quotes, a question to the viewer, \"POV: ...\".\n"
          "Rules: a full sentence with a verb, the name {login} exactly once, never \"he\" or \"she\" "
          "for the streamer, 1-2 emojis at the end, 70 chars max. "
          "Forbidden words: reaction, insane, epic, moment, and no exclamation marks.\n"
          "Already posted titles (reuse neither their shape nor their words): {recent}\n"
          "hook: 3-6 words shown big at the start, tension without spoiling.\n"
          "question: a short question to viewers about this clip, so they answer in the comments.\n"
          "tag: one hashtag about the clip's topic (no #).\n"
          "Answer only in JSON: {{\"hook\": \"...\", \"title\": \"...\", \"question\": \"...\", \"tag\": \"...\"}}",
}

FIX_FR = ("Corrige uniquement l'orthographe et la grammaire de ce titre TikTok, sans changer le sens, "
          "le ton ni les emojis : \"{title}\". Réponds uniquement en JSON : {{\"title\": \"...\"}}")

BANNED = ["reaction", "réaction", "incroyable", "épique", "epique", "insane", "epic", "moment", "dingue",
          "truc", "wzbot", "autoclip", "part1", "!"]
BAD_TAGS = ("gtarp", "gta5", "leak", "fyp", "viral", "tiktok")
REWIND = {"fr": "◀◀ quelques secondes avant", "en": "◀◀ a few seconds earlier"}


def clean_twitch_title(t):
    """« WzBot AutoCLIP : X fait Y » -> « X fait Y » : les bots de clips signent leurs titres."""
    return re.sub(r"^\s*\S*bot\b[^:]*:\s*", "", t or "", flags=re.I).strip()


HARD = ["reaction when", "réaction de", "wzbot", "autoclip"]  # jamais, même en dernier recours


def _has(low, b):
    """Mot entier (« truc » ne bloque pas « truck ») ; la ponctuation (« ! ») partout."""
    return re.search(rf"(?<!\w){re.escape(b)}(?!\w)", low) is not None if b[0].isalnum() else b in low


def bad_title(title, recent, strict=True, name=""):
    low = title.lower()
    return (not title or len(title) > 80 or any(_has(low, b) for b in (BANNED if strict else HARD))
            or low in {r.lower() for r in recent}
            or (strict and name and name.lower().rstrip("_") not in low))  # le nom fait cliquer les fans


CLAUDE = "claude-haiku-5-5"


def _claude(prompt):
    import anthropic
    try:
        r = anthropic.Anthropic().messages.create(
            model=CLAUDE, max_tokens=2000, output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}])
    except anthropic.APIError as e:
        raise ValueError(f"Claude : {e}") from e
    text = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)  # le JSON, même entouré de texte ou de ```json
    if not m:
        raise ValueError(f"Claude : pas de JSON ({r.stop_reason})")
    return json.loads(m.group(0))


def uses_claude():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _ask(model, prompt, temperature):
    if uses_claude():
        return _claude(prompt)
    r = requests.post("http://localhost:11434/api/generate", timeout=300, json={
        "model": model, "stream": False, "format": "json", "keep_alive": "30s",  # libère la RAM pour le rendu
        "options": {"temperature": temperature}, "prompt": prompt})
    r.raise_for_status()
    return json.loads(r.json()["response"])


def generate(clip, transcript, lang, model, recent=()):
    name = clip.get("name") or clip["login"]
    prompt = PROMPT[lang].format(login=name, title=clean_twitch_title(clip["title"]), transcript=transcript[:1500],
                                 recent=" | ".join(recent[:12]) or "aucun")
    data, usable = {}, None
    for temperature in (0.7, 0.9, 1.0):  # on redemande si le titre est interdit ou déjà publié
        try:
            data = _ask(model, prompt, temperature)
            if lang == "fr" and data.get("title") and not uses_claude():  # qwen fait des fautes, pas Claude
                data["title"] = _ask(model, FIX_FR.format(title=data["title"]), 0.1).get("title") or data["title"]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"titre : {e}", file=sys.stderr)  # visible dans le journal GitHub
            data = {}
        if not bad_title(str(data.get("title") or ""), recent, name=name):
            break
        if usable is None and not bad_title(str(data.get("title") or ""), recent, strict=False):
            usable = data  # un mot faible (« moment »…) vaut mieux que le titre Twitch brut (« lol »)
    else:
        data = usable or {k: v for k, v in data.items() if k != "title"}
    return finalize(data, clip, lang)


def finalize(data, clip, lang):
    """Valide la sortie du modèle et retombe sur le titre Twitch si besoin."""
    login, name = clip["login"], clip.get("name") or clip["login"]
    title = str(data.get("title") or f"{name} : {clean_twitch_title(clip['title'])} 💀")[:90]
    hook = str(data.get("hook") or clean_twitch_title(clip["title"]))[:40]
    tag = re.sub(r"[^\w]", "", str(data.get("tag") or "")).lower()
    tags = ["gta6", "gtavi", login.lower()] + ([tag] if tag and not any(b in tag for b in BAD_TAGS) else [])
    tags = list(dict.fromkeys(tags))
    question = str(data.get("question") or "").strip()
    credit = "Crédit" if lang == "fr" else "Credit"
    description = (f"{title}\n\n" + (f"{question}\n\n" if question else "")
                   + f"🎥 {credit} : twitch.tv/{login}\n\n" + " ".join("#" + t for t in tags))
    return {"hook": hook, "title": title, "description": description, "hashtags": tags, "rewind": REWIND[lang]}
