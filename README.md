# 🎬 ScreenRecorder Pro - Application d'Enregistrement d'Écran

Application professionnelle d'enregistrement d'écran pour Windows avec système de mise à jour automatique.

## ✨ Fonctionnalités Principales

### 📹 Enregistrement Vidéo Haute Qualité
- **Résolutions supportées**: HD (720p), Full HD (1080p), 2K (1440p), **4K UHD (2160p)**
- **FPS ajustables**: 24, 30, 60 FPS
- **Bitrate contrôlable**: De 2500k à 20000k pour optimiser la taille des fichiers
- **Encodage H.264** via FFmpeg pour une compression optimale

### 🔊 Gestion Audio Avancée
- Enregistrement audio synchronisé
- **Contrôle du volume/gain** (0.1x à 2.0x)
- Volume réduit par défaut (0.5x) pour un rendu "conséquemment bas"
- Format AAC 128kbps pour une qualité audio optimale

### 🔄 Système de Mise à Jour Automatique
- **Vérification automatique** au démarrage
- **Notification de nouvelle version** avec changelog
- **Téléchargement et installation** automatisés
- Barre de progression en temps réel
- Option de désactivation dans les paramètres

### 💻 Interface Utilisateur Intuitive
- Design moderne et épuré
- Chronomètre en temps réel
- Sélecteurs intelligents avec suggestions
- Statuts clairs et indicateurs visuels
- Menu complet (Fichier, Outils, Aide)

## 🚀 Installation & Déploiement sur Windows

### Option 1 : Créer un Vrai Installateur (Comme Docker/Telegram) ⭐ RECOMMANDÉ

Cette méthode génère un fichier `Setup.exe` professionnel qui installe l'application dans `C:\Program Files`, crée des raccourcis et apparaît dans "Ajouter/Supprimer des programmes".

**Prérequis :**
- Python 3.8+ installé
- [NSIS](https://nsis.sourceforge.io/Download) (outil gratuit pour créer des installateurs Windows)

**Étapes :**

```bash
# 1. Lancer le script de build automatique
build_installer.bat
```

**Ce que fait le script :**
1. Vérifie les prérequis (Python, PyInstaller)
2. Installe les dépendances Python
3. Compile l'application en un exécutable unique (`screen_recorder.exe`)
4. Génère un installateur professionnel (`ScreenRecorderPro_Setup_1.0.0.exe`)

**Résultat final :**
- Fichier créé : `dist_installer\ScreenRecorderPro_Setup_1.0.0.exe`
- Double-cliquez dessus pour installer l'application comme n'importe quel logiciel professionnel
- L'installateur ajoute :
  - Raccourci sur le Bureau
  - Entrée dans le Menu Démarrer
  - Désinstallateur dans "Paramètres > Applications"

---

### Option 2 : Utilisation Rapide (Sans Installateur)

Si vous voulez juste tester rapidement sans créer d'installateur :

```bash
# 1. Installer FFmpeg (nécessaire pour l'encodage vidéo)
choco install ffmpeg
# OU télécharger depuis https://www.gyan.dev/ffmpeg/builds/

# 2. Installer les dépendances Python
pip install -r requirements.txt

# 3. Créer l'exécutable simple
pyinstaller --onefile --windowed --name "screen_recorder" screen_recorder.py

# 4. Utiliser l'application
# Le fichier est dans : dist\screen_recorder.exe
# Copiez-le où vous voulez et double-cliquez dessus
```

---

## 🔄 Système de Mise à Jour Automatique

L'application intègre un système de mise à jour intelligent similaire aux logiciels professionnels :

### Comment ça marche ?
1. **Détection automatique** : Au démarrage, l'application vérifie la version sur votre serveur
2. **Notification** : Si une nouvelle version existe, une fenêtre pop-up informe l'utilisateur avec les notes de version
3. **Téléchargement & Installation** : L'utilisateur accepte et la mise à jour se télécharge, puis se lance automatiquement

### Comment publier une mise à jour ?

**Étape 1 :** Modifier la version dans `screen_recorder.py`
```python
APP_VERSION = "1.1.0"  # Augmentez le numéro de version
```

**Étape 2 :** Régénérer l'installateur
```bash
build_installer.bat
```

**Étape 3 :** Héberger le nouvel installateur sur votre serveur/web/cloud

**Étape 4 :** Créer/mettre à jour le fichier `version.json` sur votre serveur :

```json
{
  "latest_version": "1.1.0",
  "download_url": "https://votre-site.com/downloads/ScreenRecorderPro_Setup_1.1.0.exe",
  "release_notes": "✅ Correction de bugs\n✅ Amélioration qualité 4K\n✅ Nouveau curseur de volume"
}
```

**Étape 5 :** Mettre à jour l'URL dans `screen_recorder.py` :
```python
UPDATE_SERVER_URL = "https://votre-site.com/version.json"
```

Désormais, tous les utilisateurs recevront une notification de mise à jour au prochain lancement !

---

## 📖 Utilisation Quotidienne

### Démarrer un Enregistrement
1. Lancez l'application
2. Configurez vos paramètres:
   - **Résolution**: Choisissez HD, Full HD, 2K ou 4K
   - **FPS**: 24, 30 ou 60 selon vos besoins
   - **Bitrate**: Plus élevé = meilleure qualité mais fichier plus lourd
   - **Volume**: Réglez le gain audio (0.5 recommandé pour volume bas)
3. Cliquez sur **"▶️ Démarrer l'Enregistrement"**
4. Un chronomètre s'affiche pour suivre la durée
5. Cliquez sur **"⏹️ Arrêter"** pour terminer

### Gérer les Mises à Jour
- **Vérification automatique**: Au démarrage, l'application vérifie les nouvelles versions
- **Notification**: Une fenêtre s'affiche si une mise à jour est disponible
- **Installation**: Cliquez sur "Télécharger et Installer" pour mettre à jour
- **Manuel**: Menu → Outils → Vérifier les mises à jour

### Personnalisation
- **Dossier de sortie**: Cliquez sur "Parcourir..." pour choisir où sauvegarder vos vidéos
- **Paramètres**: Menu → Outils → Paramètres pour configurer les mises à jour automatiques

## 🔧 Configuration Technique

### Structure du Projet
```
screen_recorder/
├── screen_recorder.py      # Application principale
├── requirements.txt        # Dépendances Python
├── README.md              # Ce fichier
└── config.json            # Configuration utilisateur (généré automatiquement)
```

### Classes Principales
- `UpdateManager`: Gestion des mises à jour automatiques
- `ScreenRecorder`: Capture et encodage vidéo
- `AudioRecorder`: Capture et traitement audio
- `ScreenRecorderApp`: Interface graphique utilisateur

## 📁 Fichiers du Projet

| Fichier | Description |
|---------|-------------|
| `screen_recorder.py` | Code source principal de l'application |
| `build_installer.bat` | **Script de build** - Crée l'exécutable et l'installateur |
| `setup_installer.nsi` | Script NSIS pour générer le Setup.exe professionnel |
| `requirements.txt` | Liste des dépendances Python |
| `README.md` | Documentation complète |

## 🛠️ Développement Futur & Évolutions

Pour faire évoluer votre application comme un logiciel professionnel :

### Ajouter une Nouvelle Fonctionnalité
1. Modifiez `screen_recorder.py`
2. Incrémentez la version : `APP_VERSION = "1.1.0"`
3. Testez localement : `python screen_recorder.py`
4. Générez le nouvel installateur : `build_installer.bat`
5. Déployez le nouveau `Setup.exe` sur votre serveur

### Workflow de Mise à Jour Typique
```bash
# 1. Modifier le code source
notepad screen_recorder.py

# 2. Changer le numéro de version dans le fichier
# APP_VERSION = "1.2.0"

# 3. Reconstruire l'installateur
build_installer.bat

# 4. Tester l'installateur généré
dist_installer\ScreenRecorderPro_Setup_1.2.0.exe

# 5. Déployer sur votre serveur/cloud
# Copiez vers votre hébergement web
```

### Bonnes Pratiques
- **Versionnement sémantique** : MAJEURE.MINEURE.CORRECTIF (ex: 1.2.3)
- **Notes de version** : Tenez un journal des changements dans le fichier `version.json`
- **Tests** : Testez toujours l'installateur sur une machine propre avant déploiement
- **Backup** : Sauvegardez vos versions stables

---

## ⚠️ Notes Importantes

- **FFmpeg requis** pour l'encodage H.264 haute qualité
- **PyAudio** peut nécessiter des dépendances système supplémentaires sur Windows
- Les **permissions microphone** doivent être activées pour l'enregistrement audio
- L'application utilise **environ 200-500 MB RAM** pendant l'enregistrement
- **NSIS** est uniquement nécessaire pour créer l'installateur, pas pour utiliser l'application

---

## 🤝 Support & Dépannage

### Problèmes Courants

**"ffmpeg n'est pas reconnu"**
```powershell
# Installer FFmpeg via Chocolatey
choco install ffmpeg
```

**L'installateur ne se crée pas**
- Installez NSIS depuis https://nsis.sourceforge.io/Download
- Relancez `build_installer.bat`

**Erreurs PyAudio**
```bash
pip install pipwin
pipwin install pyaudio
```

**L'application ne détecte pas les mises à jour**
- Vérifiez que `UPDATE_SERVER_URL` pointe vers un fichier `version.json` accessible
- Assurez-vous que le serveur autorise les requêtes CORS

---

**Développé avec ❤️ en Python - Prêt pour un usage professionnel quotidien**
