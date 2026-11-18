"""Accroche, titre et hashtags générés en local par Ollama (aucun token payant)."""
import json
import re

import requests

PROMPT = {
    "fr": "Tu es un expert des titres TikTok viraux. Tu écris le titre d'un clip GTA, en français familier, "
          "comme un ado qui partage un moment de dingue à ses potes.\n"
          "Streamer : {login}. Titre Twitch du clip : \"{title}\". Ce qui est dit : \"{transcript}\".\n"
          "Choisis LA formule qui colle le mieux au clip :\n"
          "- suspense : \"{login} pensait que c'était un PNJ… 💀\"\n"
          "- réaction : \"La réaction de {login} quand il voit le prix 😭\"\n"
          "- superlatif : \"{login} a trouvé le pire bug de GTA 6 😂\"\n"
          "- citation choc tirée de ce qui est dit : \"« Me laisse pas là frérot » 😭 ({login})\"\n"
          "- POV : \"POV : t'es le passager de {login} 💀\"\n"
          "Règles : une vraie phrase avec un verbe (jamais du style télégraphique comme \"bloque voitures\"), "
          "qui dit ce qui se passe de façon concrète et crée une émotion ou une question. "
          "Le nom {login} apparaît une fois. 1 ou 2 emojis à la fin (😭💀😂🔥🤯). 70 caractères max. "
          "Interdit : \"incroyable\", \"épique\", \"moment\", les points d'exclamation, inventer ce qui n'est pas dans le clip.\n"
          "L'accroche (affichée 2 s au début de la vidéo) fait 3 à 6 mots, pose une question ou une tension "
          "sans dévoiler la fin (ex. \"Il aurait pas dû faire ça\", \"Attends la fin…\").\n"
          "Réponds uniquement en JSON : {{\"hook\": \"...\", \"title\": \"...\", \"hashtags\": [\"...\", \"...\", \"...\"]}}",
    "en": "You are an expert at viral TikTok titles. You write the title of a GTA clip in casual US English, "
          "like a teen sharing an insane moment with friends.\n"
          "Streamer: {login}. Twitch clip title: \"{title}\". What is said: \"{transcript}\".\n"
          "Pick THE formula that fits the clip best:\n"
          "- suspense: \"{login} thought it was just an NPC… 💀\"\n"
          "- reaction: \"{login}'s reaction when he sees the price 😭\"\n"
          "- superlative: \"{login} found the worst glitch in GTA 6 😂\"\n"
          "- shocking quote from what is said: \"'Bro don't leave me here' 😭 ({login})\"\n"
          "- POV: \"POV: you're riding with {login} 💀\"\n"
          "Rules: a real sentence with a verb (never telegraphic like \"blocks cars\"), "
          "saying concretely what happens and creating an emotion or a question. "
          "The name {login} appears once. 1-2 emojis at the end (😭💀😂🔥🤯). 70 chars max. "
          "Forbidden: \"insane\", \"epic\", \"moment\", exclamation marks, making up things not in the clip.\n"
          "The hook (shown for 2 s at the start of the video) is 3-6 words, raises a question or tension "
          "without spoiling the ending (e.g. \"He should NOT have done that\", \"Wait for the end…\").\n"
          "Answer only in JSON: {{\"hook\": \"...\", \"title\": \"...\", \"hashtags\": [\"...\", \"...\", \"...\"]}}",
}


def generate(clip, transcript, lang, model):
    try:
        r = requests.post("http://localhost:11434/api/generate", timeout=300, json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0.7},
            "prompt": PROMPT[lang].format(login=clip.get("name") or clip["login"], title=clip["title"], transcript=transcript[:1500])})
        r.raise_for_status()
        data = json.loads(r.json()["response"])
    except (requests.RequestException, ValueError, KeyError):
        data = {}
    return finalize(data, clip, lang)


def finalize(data, clip, lang):
    """Valide la sortie du modèle et retombe sur le titre Twitch si besoin."""
    login = clip["login"]
    title = str(data.get("title") or f"{clip.get('name') or login}: {clip['title']}")[:90]
    hook = str(data.get("hook") or clip["title"])[:40]
    tags = [re.sub(r"[^\w]", "", str(t)).lower() for t in (data.get("hashtags") or [])]
    base = ["gta6", "gtarp" if lang == "en" else "gtarpfr", login]
    tags = list(dict.fromkeys(base + [t for t in tags if t]))[:5]
    credit = "Crédit" if lang == "fr" else "Credit"
    description = f"{title}\n\n🎥 {credit} : twitch.tv/{login}\n\n" + " ".join("#" + t for t in tags)
    return {"hook": hook, "title": title, "description": description, "hashtags": tags}
