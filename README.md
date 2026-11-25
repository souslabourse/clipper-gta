# Clipper GTA — chaîne automatique de clips

Twitch → montage 9:16 + sous-titres → TikTok + YouTube Shorts (via Buffer) → récap Telegram.
Tourne gratuitement sur GitHub Actions, PC éteint.

## Fonctionnement

Toutes les heures, GitHub lance `python -m clipper tick` (fichier `.github/workflows/clipper.yml`) :
1. lit tes commandes Telegram (`/status` `/pause` `/resume` `/remove <login>` `/restore <login>` `/list`) ;
2. publie tout de suite les clips avec un invité (`vip`, ex. Léa Elui), puis, si un créneau de `config.yaml`
   est atteint, le meilleur clip prêt (FR et EN séparés) ; l'état est sauvegardé juste après ;
3. récupère les clips GTA récents, classés par **vues par heure** (× priorité du streamer), et en monte quelques-uns ;
4. à 23 h : récap Telegram ; le lundi : bilan TikTok et priorités ajustées (`learn`, si `APIFY_TOKEN`).

Un gardien (`.github/workflows/watchdog.yml`) prévient sur Telegram si aucun passage n'a réussi depuis 3 h.

L'état (base SQLite + vidéos) est sauvegardé sur la branche `data`. Les vidéos sont publiées sur
GitHub Pages (`https://souslabourse.github.io/clipper-gta/<fichier>.mp4`), car Buffer exige une URL HTTPS publique.
Les vidéos publiées sont supprimées après 24 h.

Montage : extrait de VOD avec 8 s de contexte avant et 4 s après le clip, coupe des temps morts calmes,
ouverture choc (moment fort et visible + accroche en gros, puis « quelques secondes avant »), facecam en haut
(détection auto) ou jeu en grand sur fond flouté, zooms sur les pics sonores, volume normalisé, sous-titres
mot par mot (mot actif en jaune), crédit `twitch.tv/<streamer>`. Jamais moins de 20 s ni plus de 90 s.

## Secrets (GitHub → Settings → Secrets and variables → Actions)

| Nom | Valeur |
|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | dev.twitch.tv/console |
| `CLIPPER_BUFFER_KEY_FR`, `CLIPPER_BUFFER_KEY_EN` | publish.buffer.com/settings/api (un compte Buffer gratuit par langue) |
| `CLIPPER_BUFFER_CHANNELS_FR`, `CLIPPER_BUFFER_CHANNELS_EN` | `tiktok:<id>,youtube:<id>` (ids donnés par `python -m clipper channels`) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | @BotFather, puis `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| `ANTHROPIC_API_KEY` (facultatif) | platform.claude.com → API keys : titres avec Claude Haiku (~0,30 $/mois) au lieu d'Ollama |
| `APIFY_TOKEN` (facultatif) | console.apify.com → Settings → API & Integrations : bilan TikTok du lundi (~0,30 $/semaine) |

## Réglages
Tout est dans `config.yaml` : streamers (`program`, `facecam`, `boost`, `own_subs`), invités (`vip`), durées,
créneaux, quota par jour.
Modifier le fichier sur github.com (icône crayon) suffit : le passage suivant l'utilise.
Facecam mal cadrée : `facecam: [x, y, largeur, hauteur]` en fractions de l'image, ou `facecam: none`.

Lancer un passage à la main : onglet **Actions → clipper → Run workflow**.

## Programmes de clipping (revenus)
Inscription et soumission des liens avec ton identité : Whop Content Rewards (Kai Cenat, Marlon, Clix, Silky,
JasonTheWeen), Reach (Lacy). Le récap Telegram rappelle de soumettre les clips publiés.

## Pas encore fait
Moments forts dans les VODs sans clip (pics du chat), streamers Kick (N3on).

## Tests
`python -m pytest tests` (logique pure, sans réseau).
