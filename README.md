# Arko Voice Block Challenge

Serveur Minecraft Fabric `1.21.11` prêt à déployer avec destruction de blocs à la voix, chat vocal de proximité et optimisations serveur.

## Installation serveur en un lien

Sur la machine qui hébergera le serveur :

```bash
curl -fsSL https://raw.githubusercontent.com/Priveetee/arko-voice-block-challenge/main/install.sh | bash
```

Le script installe ou met à jour le dépôt dans `~/arko-voice-block-challenge`, puis démarre Docker Compose.

Ports à transférer sur le routeur :

- Minecraft : `31877/TCP`
- Simple Voice Chat : `31878/UDP`

## Installation joueur en un lien

Télécharger le pack client depuis la [dernière release](https://github.com/Priveetee/arko-voice-block-challenge/releases/latest), puis l'importer dans Prism Launcher, Modrinth App ou un launcher compatible `.mrpack`.

Le pack installe automatiquement Fabric, Speak No Blocks, Simple Voice Chat, Fabric API, Mod Menu, Sodium et les optimisations client. La configuration française est incluse.

Au premier lancement :

1. Ouvrir la configuration de Speak No Blocks dans le menu des mods.
2. Télécharger le modèle Vosk local d'environ 1,8 Go.
3. Sélectionner le modèle téléchargé.
4. Autoriser Minecraft à utiliser le microphone.
5. Se connecter à `ADRESSE_DU_SERVEUR:31877`.

Les mots français courants sont déjà configurés : `bois`, `pierre`, `terre`, `sable`, `fer`, `diamant`, `coffre`, `four`, etc. La touche `V` ouvre la configuration de Simple Voice Chat.

## Architecture

Le mod original `DO NOT SAY THE NAME OF THIS BLOCK!` est client uniquement. Le serveur utilise donc `Speak No Blocks`, qui envoie les blocs reconnus au serveur pour que la destruction soit autoritaire et multijoueur.

La reconnaissance vocale de Speak No Blocks reste locale au client. Simple Voice Chat utilise séparément le port UDP `31878` pour la conversation de proximité.

Mods serveur épinglés : Lithium, FerriteCore, Krypton, Alternate Current, ServerCore et Spark.

## Maintenance

```bash
cd ~/arko-voice-block-challenge
docker compose ps
docker compose logs --tail=200 minecraft
```

Les données du monde restent dans `data/` et ne sont jamais publiées dans GitHub.
