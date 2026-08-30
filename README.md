# 🎬 ScreenRecorder Pro

Enregistreur d'écran professionnel pour Windows avec analyse automatique du système et interface moderne.

## ✨ Fonctionnalités

- **📹 Qualité Vidéo** : HD, Full HD, 2K, 4K
- **🔊 Volume Bas** : Réglage audio par défaut à 0.5x
- **⚖️ Fichiers Légers** : Bitrate ajustable (2500k - 20000k)
- **🤖 Analyse Système** : Détection automatique des capacités (ENTRY/STANDARD/PRO)
- **🎨 UI/UX Moderne** : Interface intuitive, thème sombre par défaut
- **🔄 Mises à Jour Auto** : Notification et installation automatiques

## 🏗️ Architecture du Projet

```
ScreenRecorderPro/
├── main.py                    # Point d'entrée principal
├── requirements.txt           # Dépendances Python
├── build_installer.bat        # Script de compilation
├── setup_installer.nsi        # Script d'installation NSIS
│
├── src/                       # Code source
│   ├── __init__.py
│   ├── core/                  # Logique métier
│   │   ├── recorder.py        # Enregistrement vidéo/audio
│   │   ├── encoder.py         # Encodage FFmpeg
│   │   └── system_analyzer.py # Analyse des performances
│   │
│   ├── ui/                    # Interface utilisateur
│   │   ├── main_window.py     # Fenêtre principale
│   │   ├── components.py      # Composants réutilisables
│   │   └── themes.py          # Thèmes et couleurs
│   │
│   └── utils/                 # Utilitaires
│       ├── updater.py         # Gestion des mises à jour
│       └── config.py          # Configuration utilisateur
│
└── assets/                    # Ressources graphiques
    ├── icons/
    └── fonts/
```

## 🚀 Installation

### 1. Prérequis

- **Windows 10/11**
- **Python 3.8+**
- **FFmpeg** : [Télécharger ici](https://www.gyan.dev/ffmpeg/builds/)

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Tester l'application

```bash
python main.py
```

## 📦 Créer un Installateur

Pour générer un exécutable et un installateur professionnel :

```cmd
build_installer.bat
```

Cela créera :
- `dist/screen_recorder.exe` - Exécutable autonome
- `dist_installer/ScreenRecorderPro_Setup_1.0.0.exe` - Programme d'installation

L'installateur va :
- ✅ Installer dans `C:\Program Files\MonEntreprise\ScreenRecorderPro`
- ✅ Créer un raccourci sur le Bureau
- ✅ Ajouter une entrée au Menu Démarrer
- ✅ Permettre la désinstallation via Paramètres Windows

## 🎯 Niveaux de Configuration

L'application détecte automatiquement votre matériel et recommande les meilleurs paramètres :

| Niveau | RAM | CPU | Résolution Max | FPS | Bitrate |
|--------|-----|-----|----------------|-----|---------|
| **ENTRY** | < 8 GB | < 4 cœurs | 720p | 30 | 2500k |
| **STANDARD** | 8-16 GB | 4-8 cœurs | 1080p | 60 | 5000k |
| **PRO** | > 16 GB | > 8 cœurs | 4K | 60 | 15000k |

## ⚙️ Paramètres Recommandés

### Pour un volume bas (défaut)
- **Gain Audio** : 0.5x (réduit le volume de 50%)
- Ajustable de 0.1x à 2.0x selon vos besoins

### Pour des fichiers légers
- **Bitrate** : 2500k - 5000k
- **Résolution** : 720p ou 1080p
- **FPS** : 30

### Pour une qualité maximale
- **Bitrate** : 15000k - 20000k
- **Résolution** : 4K
- **FPS** : 60

## 🔄 Système de Mise à Jour

### Pour les développeurs

Quand vous publiez une nouvelle version :

1. Mettre à jour la version dans `src/__init__.py` :
   ```python
   __version__ = "1.1.0"
   ```

2. Recompiler avec `build_installer.bat`

3. Déposer le nouveau Setup.exe sur votre serveur

4. Créer un fichier `version.json` sur votre serveur :
   ```json
   {
     "version": "1.1.0",
     "message": "Nouvelles fonctionnalités...",
     "download_url": "https://votre-site.com/ScreenRecorderPro_Setup_1.1.0.exe",
     "changelog": ["Feature 1", "Feature 2"]
   }
   ```

Les utilisateurs recevront une notification au prochain lancement !

## 🎨 Design & UX

- **Thème Sombre Moderne** : Réduit la fatigue visuelle
- **Couleurs** :
  - Fond : `#1e1e2e`
  - Surface : `#2a2a3e`
  - Primaire : `#7c3aed` (Violet)
  - Succès : `#10b981` (Vert)
  
- **Composants** :
  - Boutons arrondis avec effets hover
  - Badges de niveau système colorés
  - Indicateurs d'état en temps réel

## 🛠️ Développement

### Ajouter une nouvelle fonctionnalité

1. Créer le module dans le dossier approprié (`core/`, `ui/`, ou `utils/`)
2. Exporter dans le `__init__.py` correspondant
3. Importer dans `main.py` ou les autres modules

### Structure type d'un module

```python
"""
NomModule - Description courte
"""

class MaClasse:
    """Documentation de la classe"""
    
    def __init__(self):
        pass
    
    def ma_methode(self):
        """Documentation de la méthode"""
        pass
```

## 📝 Licence

Propriétaire - Tous droits réservés

## 🤝 Support

Pour toute question ou problème, contactez le support technique.