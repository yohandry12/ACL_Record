# 📘 Cahier des Charges UI/UX & Fonctionnel : Lumina Recorder

## 1. Identité de la Marque
- **Nom du produit** : Lumina
- **Slogan** : "Capturez votre monde en toute clarté."
- **Philosophie** : Simplicité radicale, puissance invisible, chaleur humaine.
- **Cible** : Du grand public (utilisateurs lambda) aux professionnels exigeants.
- **Ton** : Bienveillant, professionnel, rassurant, moderne.

---

## 2. Direction Artistique (Design System)

### Palette de Couleurs
L'interface doit évoquer la lumière et la clarté, tout en restant reposante pour les yeux lors d'utilisations longues.

- **Fond Principal (Dark Mode par défaut)** : `#0F172A` (Bleu Nuit Profond) - *Évite la fatigue oculaire.*
- **Surface / Cartes** : `#1E293B` (Gris Bleuté) - *Pour séparer les zones fonctionnelles.*
- **Couleur Primaire (Action)** : `#6366F1` (Indigo Lumineux) à `#8B5CF6` (Violet Doux) - *Dégradé pour le bouton d'enregistrement.*
- **Couleur Secondaire (Accent)** : `#38BDF8` (Ciel Clair) - *Pour les indicateurs actifs et icônes.*
- **Texte Principal** : `#F8FAFC` (Blanc Cassé) - *Lisibilité maximale.*
- **Texte Secondaire** : `#94A3B8` (Gris Ardoise) - *Pour les légendes et descriptions.*
- **Alertes/Erreurs** : `#F43F5E` (Rouge Rosé) - *Doux mais visible.*
- **Succès/Enregistrement** : `#10B981` (Émeraude) - *Indicateur "Live".*

### Typographie
- **Police Principale** : *Inter* ou *Roboto* (Sans-serif, moderne, très lisible).
- **Titres** : Gras, taille large, espacement généreux.
- **Corps de texte** : Regular, taille confortable (14px-16px).
- **Chiffres (FPS, Bitrate)** : *JetBrains Mono* ou *Roboto Mono* (pour l'aspect technique précis).

### Formes & Effets
- **Arrondis** : `border-radius: 12px` pour les cartes, `24px` pour les boutons principaux.
- **Ombres** : Douces et diffuses (`box-shadow: 0 4px 20px rgba(0,0,0,0.3)`) pour donner de la profondeur.
- **Transparence** : Utilisation de verre dépoli (Glassmorphism léger) pour les panneaux flottants.
- **Animations** : Transitions fluides (0.3s ease-in-out) sur tous les hover et changements d'état.

---

## 3. Architecture de l'Interface (Wireframes)

L'application se compose d'une **fenêtre principale unique** modulaire, divisée en 3 zones clés.

### A. En-tête (Header)
- **Logo** : Icône "Lumina" (un cercle avec un rayon de lumière stylisé) + Texte "Lumina" en gras.
- **Indicateur Système (Smart Sense)** :
    - Une petite pastille colorée indiquant le profil détecté automatiquement :
        - 🟢 **Pro** (Config haute : 4K possible)
        - 🟠 **Standard** (Config moyenne : 1080p optimisé)
        - 🔵 **Entry** (Config faible : 720p léger)
    - *Tooltip au survol* : "Votre PC est configuré pour une performance optimale en 1080p."
- **Bouton Paramètres** : Icône engrenage discrète.
- **Bouton Mise à jour** : Icône cloche avec point rouge si mise à jour disponible.

### B. Zone Centrale (Le Cœur de l'Action)
C'est la zone la plus grande, épurée, centrée sur l'action.

1. **Le Bouton "Record" (Hero Element)** :
    - Un grand bouton circulaire ou pill-shape au centre.
    - **État Repos** : Dégradé Indigo/Violet, texte "Démarrer l'enregistrement".
    - **État Hover** : Légère élévation, brillance accrue.
    - **État Enregistrement** : Devient Rouge/Émeraude, pulse doucement, texte "En cours...".
    - **Icône** : Un point rouge simple ou un cercle épais.

2. **Sélecteur de Zone (Overlay)** :
    - Option : "Plein écran" vs "Zone personnalisée".
    - Si "Zone personnalisée" : Affiche un rectangle redimensionnable avec poignées sur l'écran.

### C. Panneau de Configuration (Bas de page ou Latéral)
Présenté sous forme de **Cartes (Cards)** horizontales ou verticales. Chaque carte a un titre, une valeur actuelle et un slider/selector.

#### Carte 1 : Qualité Vidéo (Smart Quality)
- **Label** : "Résolution & Fluidité"
- **Affichage** : `1920x1080 @ 60 FPS`
- **Contrôle** :
    - Menu déroulant simplifié : "Automatique (Recommandé)", "HD (720p)", "Full HD (1080p)", "2K", "4K".
    - *Note UX* : Si l'utilisateur choisit une résolution supérieure à son profil système, afficher un warning doux : "⚠️ Votre configuration pourrait ralentir. Restez en 1080p pour la fluidité."

#### Carte 2 : Poids & Compression (Lightweight)
- **Label** : "Taille du fichier"
- **Affichage** : `Estimé: ~150 Mo/min`
- **Contrôle** : Slider horizontal.
    - Gauche : "Ultra Léger" (Bitrate bas, idéal pour tutos).
    - Droite : "Qualité Studio" (Bitrate haut, idéal montage).
    - Curseur intelligent qui se place automatiquement sur "Équilibré" selon le profil système.

#### Carte 3 : Audio & Volume (Silent Mode)
- **Label** : "Son & Micro"
- **Contrôles** :
    - Toggle Switch : "Microphone" (On/Off).
    - Toggle Switch : "Son Système" (On/Off).
    - **Slider de Gain** : "Volume de sortie".
        - Par défaut réglé sur `0.5x` (Bas) comme demandé.
        - Échelle visuelle : De 🤫 (Silencieux) à 🔊 (Fort).
        - Indication textuelle : "Volume réduit pour confort d'écoute".

### D. Pied de page (Footer)
- **Chemin de sauvegarde** : `C:\Users\...\Videos\Lumina` + Bouton "Changer".
- **Derniers enregistrements** : Liste rapide de 3 derniers fichiers avec miniature et bouton "Ouvrir".
- **Statut disque** : Petite barre indiquant l'espace libre restant.

---

## 4. Flux Utilisateur (User Flow)

### Scénario 1 : Premier Lancement (Onboarding)
1. L'utilisateur lance `Lumina.exe`.
2. **Analyse Système (Splash Screen)** : Logo Lumina qui pulse + Texte "Analyse de votre configuration..." (Barre de progression rapide).
3. **Résultat** : La fenêtre principale s'ouvre. Une notification "Toast" apparaît en haut à droite :
   > "✨ Configuration détectée : **Standard**. Nous avons optimisé les réglages pour vous."
4. L'utilisateur voit le bouton "Démarrer" clignoter doucement pour l'inviter à agir.

### Scénario 2 : Enregistrement Quotidien
1. L'utilisateur ouvre Lumina.
2. Il vérifie que le volume est bien bas (défaut).
3. Il clique sur le gros bouton central.
4. Un compte à rebours visuel (3, 2, 1) apparaît à l'écran avec un son doux.
5. L'enregistrement commence. Une petite barre flottante (minimisée) apparaît en coin d'écran avec :
   - Temps écoulé.
   - Bouton Pause/Stop.
   - Indicateur CPU/RAM (discret).
6. L'utilisateur clique sur "Stop".
7. Notification : "✅ Enregistrement sauvegardé ! (12 Mo)".
8. Le fichier est accessible directement depuis le footer.

### Scénario 3 : Mise à Jour Automatique
1. Au lancement, l'app contacte le serveur.
2. Si nouvelle version : Une modale élégante apparaît.
   - Titre : "Une nouvelle lumière vous attend ✨"
   - Corps : "La version 1.2.0 améliore la compression 4K."
   - Bouton : "Mettre à jour maintenant" (L'app se met à jour seule et redémarre).

---

## 5. Détails Techniques pour le Designer (Mockup)

- **Grille** : Utiliser une grille de 12 colonnes, marge de 24px.
- **Espacement** : Utiliser des multiples de 8px (8, 16, 24, 32, 48).
- **Iconographie** : Style "Line Art" fin, coins arrondis, remplissage partiel au survol.
- **Accessibilité** : Contraste AA minimum respecté. Les boutons importants doivent être identifiables sans couleur (forme + texte).
- **Responsive** : La fenêtre doit pouvoir être redimensionnée (min 800x600) sans casser la mise en page (les cartes passent de horizontales à verticales si nécessaire).

---

## 6. Éléments Différenciants (USP) à mettre en avant visuellement

1. **Le Badge "Smart Sense"** : Montrer visuellement que l'app "comprend" le PC de l'utilisateur. C'est un gage de confiance.
2. **Le Slider de Volume Bas** : Mettre en évidence que par défaut, le son est doux ("Confort Auditif").
3. **L'Estimation de Poids** : Afficher clairement "Fichier léger" pour rassurer sur l'espace disque.

---

## 7. Instructions pour la génération d'image (Prompt suggéré)

> "UI design of a modern desktop screen recording application named 'Lumina'. Dark mode interface with deep blue background (#0F172A) and soft indigo/violet gradients. Central large circular record button glowing softly. Three clean cards below for Video Quality, File Size, and Audio Volume (slider set to low). Top right shows a 'System: Standard' badge. Minimalist, clean, glassmorphism touches, high fidelity, UX focused, professional software aesthetic like Discord or OBS but simpler and warmer."
