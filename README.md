# Arko Voice Block Challenge

Serveur Minecraft Fabric `1.21.11` où les joueurs détruisent les blocs en
parlant français, avec Simple Voice Chat conservé pour le chat de proximité.

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

Les joueurs n’installent pas `Speak No Blocks`, ne téléchargent aucun modèle
Whisper/Vosk et ne configurent aucune reconnaissance vocale. Ils gardent leur
installation Simple Voice Chat existante, puis se connectent à :

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

Ce pack ne contient ni `Speak No Blocks` ni modèle de reconnaissance vocale.

## Fonctionnement

`Speak No Blocks` est un mod Fabric serveur uniquement. Il segmente les phrases
avec VAD, attend leur fin, vérifie la confiance Whisper et applique la
destruction sur le thread serveur. Une phrase naturelle comme « j’ai trouvé de
l’or » ou « il y a de l’eau » déclenche le bloc correspondant ; une description
comme « le truc jaune » ne déclenche rien.

Le vocabulaire est généré au démarrage depuis les registres Minecraft chargés,
les traductions françaises des mods et les noms d’items. Il couvre aussi les
entités et les blocs ajoutés par d’autres mods, sans liste de cibles à maintenir.

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
