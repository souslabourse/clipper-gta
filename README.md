# Clipper GTA — chaîne automatique de clips

Twitch → montage 9:16 + sous-titres → TikTok + YouTube Shorts (via Buffer) → récap Telegram.
Tourne seul sur un serveur, PC éteint.

## Ce que fait le système

| Quand | Quoi |
|---|---|
| Toutes les heures | Récupère les clips les plus vus (48 h) des streamers de `config.yaml`, en GTA VI / GTA V, puis en monte 6 |
| Toutes les 10 min | Si un créneau de publication est atteint : publie le meilleur clip prêt (FR et EN séparés) |
| 23 h 30 | Récap Telegram : clips publiés, stock, état |
| En continu | Bot Telegram : `/status` `/pause` `/resume` `/remove <login>` `/restore <login>` `/list` |

Montage : extrait de VOD avec 8 s de contexte avant et 4 s après le clip, coupe des temps morts (blancs calmes),
démarrage sur la première parole (hook), facecam en haut (détection automatique), jeu en bas, sous-titres mot par mot
(mot actif en jaune), accroche en haut pendant 2,5 s, crédit `twitch.tv/<streamer>`. Jamais moins de 20 s.

## Installation (à faire une fois, ~45 min)

### 1. Comptes à créer (toi seul peux le faire)
1. **Oracle Cloud** : cloud.oracle.com → compte gratuit (carte demandée, 0 € débité), puis
   *Billing → Upgrade to Pay As You Go* (reste gratuit, évite la suppression des machines « inactives »).
   Créer une instance **Ubuntu 24.04, Ampere A1, 2 OCPU / 12 Go**, ajouter ta clé SSH.
   Dans *Networking → VCN → Security List*, ouvrir les ports **80 et 443** (TCP, 0.0.0.0/0).
   Si Oracle répond « Out of capacity » : prendre un Hetzner CAX21 (Ubuntu 24.04), même procédure.
2. **Twitch** : dev.twitch.tv/console → *Register Your Application* (OAuth Redirect : `http://localhost`,
   catégorie *Other*) → noter Client ID et Client Secret.
3. **TikTok + YouTube** : 1 compte TikTok FR, 1 TikTok EN, 1 chaîne YouTube FR, 1 chaîne YouTube EN.
   Remplis le profil et scrolle un peu à la main sur chaque TikTok (un compte neuf qui publie direct paraît suspect).
4. **Buffer** : 1 compte gratuit pour le FR (TikTok FR + YouTube FR), 1 pour l'EN. Dans chacun :
   connecter les 2 chaînes, puis publish.buffer.com/settings/api → créer une clé.
5. **Telegram** : parler à @BotFather → `/newbot` → noter le token. Envoyer un message à ton bot,
   puis ouvrir `https://api.telegram.org/bot<TOKEN>/getUpdates` pour lire ton `chat.id`.

### 2. Installer sur le serveur
Depuis ton PC (PowerShell) :
```powershell
scp -r "C:\Users\PCarthur\Documents\projet claude\projet 6 cliping" ubuntu@IP_DU_SERVEUR:~/clipper
ssh ubuntu@IP_DU_SERVEUR
```
Sur le serveur :
```bash
sudo bash ~/clipper/deploy/setup.sh      # ~15 min, affiche l'URL publique à la fin
sudo nano /etc/clipper.env               # coller les clés (Twitch, Buffer, Telegram)
sudo systemd-run --pipe --wait -p EnvironmentFile=/etc/clipper.env -p User=clipper \
  -p WorkingDirectory=/opt/clipper /opt/clipper/.venv/bin/python -m clipper channels
# -> recopier les ids dans BUFFER_CHANNELS_FR / BUFFER_CHANNELS_EN de /etc/clipper.env
sudo systemctl restart clipper-bot
sudo systemctl start clipper-run         # premier passage tout de suite
```

### 3. Vérifier
- Telegram : envoyer `/status` au bot → il répond.
- `journalctl -u clipper-run -n 50` → pas d'erreur ; `/status` montre des clips `ready`.
- Ouvrir `https://<ip-avec-tirets>.sslip.io/v/` → « 404 » = le serveur HTTPS répond.

## Réglages
Tout est dans `config.yaml` (puis `sudo cp config.yaml /opt/clipper/`) :
streamers (`program`, `facecam`), durées, créneaux, quota par jour.
Facecam mal cadrée pour un streamer : `facecam: [x, y, largeur, hauteur]` en fractions de l'image
(ex. `[0.0, 0.3, 0.2, 0.2]`), ou `facecam: none`.

## Programmes de clipping (revenus)
L'inscription et la soumission des liens se font **avec ton identité** (paiements, vérification) :
- Whop Content Rewards : whop.com → chercher la campagne du streamer (Kai Cenat, Marlon, Clix, Silky, JasonTheWeen).
- Lacy : programme via Reach (lien dans `config.yaml`).
Le récap Telegram te rappelle de soumettre les clips publiés.

## Pas encore fait (après la sortie)
Analyse de viralité hebdomadaire automatique (Apify), détection de moments forts dans les VODs sans clip,
boucle d'apprentissage sur tes stats, streamers Kick (N3on).

## Tests
`python -m pytest tests` (logique pure, sans réseau).
