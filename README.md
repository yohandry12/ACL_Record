# Enregistreur d'Écran Pro (HD/4K)

Cette application Python permet d'enregistrer votre écran avec une qualité professionnelle (HD, 2K, 4K) tout en contrôlant précisément le poids du fichier et le volume audio.

## Fonctionnalités Clés

1.  **Qualité Variable** : Support de la HD (720p), Full HD (1080p), 2K (1440p) et 4K (2160p).
2.  **Compression Intelligente** : Utilisation de l'encodage H.264 via FFmpeg pour un rendu clair mais léger.
3.  **Contrôle du Bitrate** : Réglez la qualité vidéo (de "Léger" à "Ultra") pour influencer directement la taille du fichier.
4.  **Gestion Audio** : Curseur de gain pour amplifier ou réduire le volume d'entrée lors du traitement final.
5.  **Interface Simple** : Démarrage/Arrêt facile avec indication d'état.

## Prérequis

Vous devez avoir **Python 3** installé ainsi que **FFmpeg** (indispensable pour le traitement vidéo final).

### 1. Installation de FFmpeg
*   **Windows** : Téléchargez les builds sur [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), extrayez-le et ajoutez le dossier `bin` à vos variables d'environnement PATH.
*   **Mac** : `brew install ffmpeg`
*   **Linux** : `sudo apt install ffmpeg`

### 2. Installation des librairies Python
Ouvrez un terminal dans le dossier du projet et lancez :

```bash
pip install mss numpy opencv-python pyaudio pyautogui
```
*(Note: Pour pyaudio sur Windows, il peut être nécessaire d'installer les "Visual C++ Build Tools" si l'installation échoue).*

### 3. (Optionnel) Pour tests sans écran (Linux Headless)
Si vous testez sur un serveur sans interface graphique :
```bash
sudo apt-get install xvfb xauth
xvfb-run python screen_recorder.py
```

## Utilisation

1.  Lancez l'application :
    ```bash
    python screen_recorder.py
    ```
2.  **Configuration** :
    *   Choisissez la résolution (ex: 3840x2160 pour la 4K).
    *   Ajustez le bitrate (ex: 20000k pour de la 4K nette, ou moins pour un fichier plus petit).
    *   Réglez le volume audio si nécessaire.
3.  Cliquez sur **DÉMARRER L'ENREGISTREMENT**.
4.  Faites vos actions à l'écran.
5.  Cliquez sur **ARRÊTER**. L'application va traiter la vidéo (compression) et la sauvegarder dans le dossier choisi (par défaut `~/Videos`).

## Comment ça marche ?

*   **Capture** : Utilise `mss` pour capturer l'écran rapidement et `opencv` pour écrire le flux brut.
*   **Post-Production** : À l'arrêt, le script appelle `FFmpeg` en arrière-plan. C'est cette étape qui convertit la vidéo lourde brute en un fichier MP4 H.264 optimisé et applique le filtre de volume demandé.
