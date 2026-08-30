# ✨ Lumina Recorder

> **Capturez votre monde en toute clarté**

Application d'enregistrement d'écran professionnelle pour Windows, avec intelligence artificielle et adaptation automatique aux configurations système.

---

## 🚀 Fonctionnalités Principales

### 🎯 Phase 1 - Fondation (Implémentée)
- ✅ **Analyse Système Intelligente** : Détection automatique CPU/RAM/GPU
- ✅ **Profils Adaptatifs** : ENTRY / STANDARD / PRO selon le matériel
- ✅ **Enregistrement HD/4K** : Jusqu'à 3840x2160 @ 60 FPS
- ✅ **Encodage Optimisé** : FFmpeg H.264 avec contrôle du bitrate
- ✅ **Volume Audio Réglable** : Curseur 0.1x - 2.0x (défaut 0.5x)
- ✅ **Interface Moderne** : Design épuré avec couleurs Lumina
- ✅ **Système de Mise à Jour** : Vérification automatique

### 🔮 Futures Phases
- 🔄 Smart Focus (suivi de zone active)
- 🔄 Clean Canvas (masquage notifications)
- 🔄 Sous-titres automatiques (IA Whisper)
- 🔄 Magic Cut (découpage des silences)
- 🔄 Mode CLI pour automatisation
- 🔄 OCR temps réel
- 🔄 Flou dynamique (confidentialité)
- 🔄 Assistant vocal

---

## 📁 Structure du Projet

```
LuminaRecorder/
├── main.py                    # Point d'entrée principal
├── requirements.txt           # Dépendances Python
├── build_installer.bat        # Script de compilation Windows
├── setup_installer.nsi        # Script NSIS pour Setup.exe
│
├── src/                       # Code source
│   ├── core/                  # Moteurs principaux
│   │   ├── system_analyzer.py # Analyse matérielle
│   │   ├── recorder_core.py   # Capture écran/audio
│   │   └── encoder.py         # Encodage FFmpeg
│   │
│   ├── ui/                    # Interface utilisateur
│   │   ├── main_window.py     # Fenêtre principale
│   │   └── components.py      # Composants UI
│   │
│   └── utils/                 # Outils utilitaires
│       ├── config_manager.py  # Gestion configuration
│       └── updater.py         # Mises à jour auto
│
├── config/                    # Fichiers de configuration
│   └── default_config.ini
│
└── assets/                    # Ressources graphiques
    ├── icons/
    └── fonts/
```

---

## 🛠️ Installation & Développement

### Prérequis
1. **Python 3.8+** : [Télécharger](https://www.python.org/downloads/)
2. **FFmpeg** : [Télécharger](https://www.gyan.dev/ffmpeg/builds/)
   - Extraire et ajouter `bin` au PATH système

### Installation des dépendances
```bash
cd LuminaRecorder
pip install -r requirements.txt
```

### Lancement en mode développement
```bash
python main.py
```

### Création de l'exécutable Windows
```bash
build_installer.bat
```

Cela génère :
- `dist/LuminaRecorder.exe` : Version portable
- `dist_installer/Lumina_Setup_1.0.0.exe` : Programme d'installation

### Création du Setup.exe (optionnel)
Installez [NSIS](https://nsis.sourceforge.io/Download), puis :
```bash
makensis setup_installer.nsi
```

---

## 🎨 Identité Visuelle

### Couleurs Lumina
| Usage | Couleur | HEX |
|-------|---------|-----|
| Primaire | Bleu Nuit | `#1E1B4B` |
| Accent | Indigo | `#4F46E5` |
| Succès | Vert Émeraude | `#059669` |
| Danger | Rouge Doux | `#DC2626` |
| Fond | Blanc Pur | `#FFFFFF` |

### Typographie
- **Titres** : Segoe UI Bold
- **Corps** : Segoe UI Regular
- **Chiffres** : Consolas/Mono

---

## ⚙️ Configuration

Le fichier `config/default_config.ini` contient les paramètres par défaut :

```ini
[recording]
default_resolution = auto
default_fps = 30
audio_gain = 0.5

[output]
format = mp4
codec = h264
```

L'application crée un fichier utilisateur dans :
- Windows : `%APPDATA%\LuminaRecorder\lumina_config.ini`
- Linux : `~/.config/lumina_recorder/lumina_config.ini`

---

## 🔄 Système de Mise à Jour

Pour activer les mises à jour automatiques :

1. Hébergez un fichier `version.json` sur votre serveur :
```json
{
    "version": "1.1.0",
    "release_notes": "Nouveautés:\n- Smart Focus\n- Correction de bugs",
    "download_url": "https://votre-serveur.com/Lumina_Setup_1.1.0.exe",
    "mandatory": false,
    "release_date": "2025-01-15"
}
```

2. Mettez à jour l'URL dans `src/utils/updater.py`

---

## 📊 Profils Système Détectés

| Profil | CPU | RAM | Qualité Max | FPS | Bitrate |
|--------|-----|-----|-------------|-----|---------|
| **ENTRY** | < 4 cœurs | < 8 Go | 720p | 30 | 2500k |
| **STANDARD** | 4-8 cœurs | 8-16 Go | 1080p | 60 | 6000k |
| **PRO** | > 8 cœurs | > 16 Go | 4K | 60 | 15000k |

---

## 📝 Licence

© 2025 Lumina Recorder - Tous droits réservés

---

## 🤝 Contribution

1. Fork le projet
2. Créez une branche (`git checkout -b feature/NouvelleFonctionnalite`)
3. Committez (`git commit -m 'Ajout nouvelle fonctionnalité'`)
4. Push (`git push origin feature/NouvelleFonctionnalite`)
5. Ouvrez une Pull Request

---

## 📞 Support

- Site web : https://lumina-recorder.com
- Email : support@lumina-recorder.com
- Documentation : https://docs.lumina-recorder.com

---

**Développé avec ❤️ pour les créateurs de contenu**
