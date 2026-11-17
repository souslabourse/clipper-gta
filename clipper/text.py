"""Accroche, titre et hashtags générés en local par Ollama (aucun token payant)."""
import json
import re

import requests

PROMPT = {
    "fr": "Tu écris pour TikTok en français familier. Clip GTA du streamer {login}. "
          "Titre Twitch : \"{title}\". Transcription : \"{transcript}\".\n"
          "Réponds en JSON : {{\"hook\": accroche choc de 3 à 6 mots, "
          "\"title\": titre au format '{login} + action + rebondissement' avec 1 ou 2 emojis parmi 😭💀😂🔥, "
          "max 80 caractères, \"hashtags\": 3 hashtags pertinents sans #}}. Ne révèle pas la chute dans l'accroche.",
    "en": "You write TikTok captions in casual US English. GTA clip of streamer {login}. "
          "Twitch title: \"{title}\". Transcript: \"{transcript}\".\n"
          "Answer in JSON: {{\"hook\": punchy 3-6 word hook, "
          "\"title\": title formatted '{login} + action + twist' with 1-2 emojis from 😭💀😂🔥, "
          "max 80 chars, \"hashtags\": 3 relevant hashtags without #}}. Don't spoil the payoff in the hook.",
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
