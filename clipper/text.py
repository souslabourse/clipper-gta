"""Accroche, titre et hashtags générés en local par Ollama (aucun token payant)."""
import json
import re

import requests

PROMPT = {
    "fr": "Tu écris le titre d'un clip TikTok GTA, en français familier.\n"
          "Streamer : {login}. Titre Twitch du clip : \"{title}\". Ce qui est dit : \"{transcript}\".\n"
          "Exemples de bons titres : \"Michou se fait braquer par un PNJ 😭\", "
          "\"Squeezie tente le plus gros saut de GTA 6 💀\", \"JLTomy finit en prison pour rien 😂\".\n"
          "Règles : le titre commence par le nom du streamer et décrit précisément ce qui se passe dans le clip, "
          "1 ou 2 emojis (😭💀😂🔥), 80 caractères max. "
          "L'accroche fait 3 à 6 mots, donne envie de regarder sans dévoiler la fin (ex. \"Il s'attendait pas à ça\").\n"
          "Réponds uniquement en JSON : {{\"hook\": \"...\", \"title\": \"...\", \"hashtags\": [\"...\", \"...\", \"...\"]}}",
    "en": "You write the title of a GTA TikTok clip, in casual US English.\n"
          "Streamer: {login}. Twitch clip title: \"{title}\". What is said: \"{transcript}\".\n"
          "Good title examples: \"Kai Cenat gets robbed by an NPC 😭\", \"xQc tries the biggest jump in GTA 6 💀\", "
          "\"Lacy ends up in jail for nothing 😂\".\n"
          "Rules: the title starts with the streamer's name and says exactly what happens in the clip, "
          "1-2 emojis (😭💀😂🔥), 80 chars max. "
          "The hook is 3-6 words, makes people watch without spoiling the ending (e.g. \"He did NOT see this coming\").\n"
          "Answer only in JSON: {{\"hook\": \"...\", \"title\": \"...\", \"hashtags\": [\"...\", \"...\", \"...\"]}}",
}


def generate(clip, transcript, lang, model):
    try:
        r = requests.post("http://localhost:11434/api/generate", timeout=300, json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0.7},
            "prompt": PROMPT[lang].format(login=clip["login"], title=clip["title"], transcript=transcript[:1500])})
        r.raise_for_status()
        data = json.loads(r.json()["response"])
    except (requests.RequestException, ValueError, KeyError):
        data = {}
    return finalize(data, clip, lang)


def finalize(data, clip, lang):
    """Valide la sortie du modèle et retombe sur le titre Twitch si besoin."""
    login = clip["login"]
    title = str(data.get("title") or f"{login}: {clip['title']}")[:90]
    hook = str(data.get("hook") or clip["title"])[:40]
    tags = [re.sub(r"[^\w]", "", str(t)).lower() for t in (data.get("hashtags") or [])]
    base = ["gta6", "gtarp" if lang == "en" else "gtarpfr", login]
    tags = list(dict.fromkeys(base + [t for t in tags if t]))[:5]
    credit = "Crédit" if lang == "fr" else "Credit"
    description = f"{title}\n\n🎥 {credit} : twitch.tv/{login}\n\n" + " ".join("#" + t for t in tags)
    return {"hook": hook, "title": title, "description": description, "hashtags": tags}
