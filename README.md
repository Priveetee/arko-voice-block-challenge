# Arko Voice Block Challenge

Serveur Minecraft Fabric `1.21.11` où les joueurs détruisent les blocs, items
et entités en parlant français, avec Simple Voice Chat conservé pour le chat de
proximité.

## Installation en un lien

Sur la machine Linux qui possède le GPU NVIDIA et qui hébergera le serveur :

```bash
curl -fsSL https://raw.githubusercontent.com/Priveetee/arko-voice-block-challenge/main/install.sh | bash
```

Le script clone le dépôt dans `~/arko-voice-block-challenge`, télécharge une
seule fois le modèle français faster-whisper (environ 3 Go), construit le
service CUDA local et démarre Minecraft. Le modèle est ensuite utilisé hors
ligne : aucune voix ne quitte la machine.

Pré-requis serveur : Docker Compose, pilote NVIDIA fonctionnel (`nvidia-smi`)
et support GPU NVIDIA pour Docker. Le modèle Hugging Face est public ; si un
miroir nécessite une authentification, le token peut être fourni uniquement
pour l’installation avec `HF_TOKEN=...` et n’est jamais enregistré par le
projet.

Ports à transférer sur le routeur :

- Minecraft : `31877/TCP`
- Simple Voice Chat : `31878/UDP`

## Installation joueur

Les joueurs installent le petit mod `Speak No Blocks` inclus dans le pack Prism
et gardent Simple Voice Chat. Ce mod client ne contient ni modèle, ni moteur de
reconnaissance, ni configuration micro : il affiche seulement le compte à
rebours HUD envoyé par le serveur. Ils se connectent ensuite à :

```text
ADRESSE_DU_SERVEUR:31877
```

La touche `V` ouvre la configuration de Simple Voice Chat. Son micro reste le
transport audio ; le serveur décode les paquets Opus et fait la reconnaissance
française sur le GPU.

Pour préparer automatiquement cette installation joueur dans Prism Launcher,
importe ce lien :

```text
https://github.com/Priveetee/arko-voice-block-challenge/releases/latest/download/arko-voice-block-challenge.mrpack
```

Ce pack contient le HUD client et les optimisations Sodium, Lithium, FerriteCore,
ImmediatelyFast, EntityCulling et Dynamic FPS. Il ne contient aucun modèle de
reconnaissance vocale.

## Fonctionnement

`Speak No Blocks` fait toute la logique de jeu côté serveur. Il segmente les phrases
avec VAD, attend leur fin, vérifie la confiance Whisper et applique la
destruction sur le thread serveur. Une phrase naturelle comme « j’ai trouvé de
l’or » ou « il y a de l’eau » déclenche la cible correspondante ; une
description comme « le truc jaune » ne déclenche rien.

Chaque déclenchement affiche `5 4 3 2 1` en haut à gauche, en remplaçant le
chiffre précédent, puis détruit la cible. Le rayon vocal est d’environ `513x513`
(`radius: 256`) et le rayon d’un nom exact écrit dans le chat atteint `1025x1025`
(`cheatRadius: 512`). Les chunks hors vue sont chargés/générés puis parcourus.
Les blocs ciblés, les items ciblés et les entités non hostiles correspondantes
sont supprimés ; les monstres hostiles, dont l’Ender Dragon, sont toujours
exclus, y compris au dernier contrôle avant suppression.

Le vocabulaire est généré au démarrage depuis les registres Minecraft chargés,
les traductions françaises des mods et les noms d’items. Ainsi « pioche »
correspond à toutes les pioches, les pluriels d’entités comme « slimes » sont
acceptés, et les blocs ajoutés par d’autres mods sont couverts sans liste de
cibles à maintenir.

Le chat reste normal. Écrire exactement `terre`, `eau`, `diamant`, etc. est la
commande de challenge et n’est pas réaffiché dans le chat ; les phrases
ordinaires restent visibles. Une recette serveur ajoute aussi la `Potion de gamble`, une vraie
potion jetable vanilla : elle tente de récupérer une ressource récemment bannie
pour toute l’équipe ; en cas d’échec, un autre bloc aléatoire est banni et
disparaît.

## Maintenance

```bash
cd ~/arko-voice-block-challenge
git pull --ff-only
./provision-model.sh
docker compose up -d --build --remove-orphans
docker compose ps
```

Les données du monde restent dans `data/`, le cache du modèle dans
`asr-models/`, et ces deux répertoires ne sont jamais publiés dans GitHub.
