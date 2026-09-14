# Lumina Recorder — feuille de route après la 1.5.0

Date : 14 septembre 2026. Validée avec l'utilisateur à l'issue d'un
brainstorming cadré par trois questions.

## Cadre

- **Public visé** : formateurs (cours, démonstrations logicielles) et
  créateurs de contenu (YouTube, réseaux).
- **Douleurs déclarées** : sur les trois phases — préparation (zone,
  micro, bureau), enregistrement (erreurs, reprises, repères), montage
  (couper, sous-titrer, exporter).
- **Garde-fous** : tout doit fonctionner hors ligne (un LLM distant reste
  optionnel, jamais requis) ; le socle reste sous 300 Mo, tout ce qui est
  lourd part en extension téléchargeable ; aucun compte, aucune
  télémétrie, aucune donnée envoyée sans action explicite.

## État constaté (inventaire du 14 septembre)

Le socle couvre : capture mss + FFmpeg avec profils adaptatifs, Smart
Focus, raccourci global, micro et son système, chaîne de filtres temps
réel (flou de confidentialité OCR, Clean Canvas, overlay système,
webcam), post-traitements (sous-titres Whisper, Magic Cut, miniatures,
correction et résumé par LLM), fournisseurs LLM locaux ou distants avec
clés dans le coffre Windows, capsule PyWebView, mise à jour par releases
GitHub, extensions officielles (sous-titres, OCR) et plugins utilisateur.

Trou principal découvert pendant l'inventaire : **mss ne capture pas le
pointeur de la souris** et rien dans Lumina ne le dessine. La clé
`[recording] cursor_visible` existe dans le .ini mais n'est lue nulle
part. Un tutoriel enregistré avec Lumina n'a aucun pointeur visible.

## A. Améliorations du socle

Notation : valeur ★ à ★★★ / effort.

### Préparation

1. **Curseur et halo de clic** — ★★★ / faible. Filtre temps réel qui
   dessine le pointeur (position Win32) et un cercle ambré discret à
   chaque clic. Corrige l'absence de pointeur ; prérequis du zoom
   automatique (E2). **Première spec : `2026-09-14-curseur-design.md`.**
2. **Choix de l'écran et zone libre** — ★★★ / moyen. Liste des moniteurs
   et rectangle dessiné à la souris. Aujourd'hui `monitors[1]` est en
   dur dans `recorder_core.py` : pas de multi-écran.
3. **Vu-mètre micro et son système** dans l'onglet Audio, plus une alerte
   « micro silencieux » dix secondes après le démarrage — ★★★ / faible.
   Évite les prises muettes découvertes trop tard.

### Enregistrement

4. **Marqueurs au clavier** — ★★★ / moyen. Une touche pose un horodatage.
   Sorties : fichier de chapitres au format YouTube, chapitres dans le
   résumé LLM, et une touche « reprise » qui fait couper par le
   post-traitement le segment depuis le dernier marqueur.
5. **Prompteur / notes invisibles** — ★★ / faible. Petite fenêtre texte
   flottante exclue de la capture par le même mécanisme
   (`WDA_EXCLUDEFROMCAPTURE`) que la capsule.

### Montage

6. **Rognage automatique début et fin** (secondes du clic sur REC et sur
   Stop) — ★★ / très faible.
7. **Sous-titres incrustés** dans la vidéo via FFmpeg `subtitles=` —
   ★★ / faible. Option de l'extension sous-titres, moteur FFmpeg déjà
   présent.
8. **Export vertical 9:16 et clip court** — ★★ / moyen. Post-traitement
   FFmpeg, pour les réseaux.
9. **Filigrane** : logo PNG dans un coin — ★ / très faible.
10. **« Retrouver un moment »** — ★ / faible. Interface sur la recherche
    plein-texte OCR déjà implémentée (`OCRService.search_text`,
    `export_text`), sans UI aujourd'hui.

## B. Extensions à concevoir (hors socle, hors ligne)

- **E1 Réduction de bruit micro** — `noisereduce` ou RNNoise, ~20 Mo.
  Post-traitement audio. Formateurs équipés d'un micro portable. ★★★.
- **E2 Zoom automatique sur les clics** — post-traitement qui recadre et
  zoome autour des clics, style Screen Studio. Dépend d'un journal de
  clics que le socle n'écrit pas encore (à ajouter quand E2 sera
  spécifiée, pas avant). ★★★ / élevé.
- **E3 Traduction de sous-titres hors ligne** — Argos Translate, ~100 Mo
  par paire de langues, en aval de Whisper. ★★.
- **E4 Fond de webcam flouté ou remplacé** — MediaPipe, ~30 Mo. ★★.
- **E5 Voix off locale** — Piper TTS, ~60 Mo. En réserve : risque de
  gadget.

## C. Dette à régler en passant (un commit chacun, sans spec)

- `README.md` obsolète : liste comme « futures » des fonctions livrées,
  ne mentionne ni webcam, ni plugins, ni extensions, ni fournisseurs LLM.
- `config/default_config.ini` en retard : `version = 1.0.0`, et l'UI
  écrit des clés absentes du fichier de référence (`smart_focus`,
  `system_audio`, `magic_cut_max`, `delete_original`, `thumbnails`,
  `summary`, `subtitle_fix`, `provider`, `model`, `plugins.actifs`,
  `check_on_start`).
- CLI `services/cli_interface.py` écrite (sept commandes) mais jamais
  branchée : brancher ou supprimer.
- Doublons : `utils/updater.py` (version.json) face à
  `services/update_checker.py` ; `ai/smart_focus.py` face à
  `core/focus_tracker.py` ; `LuminaAIService` face à `AITasks` ;
  `OCRService._simulate_ocr` contraire à la règle « rien n'est simulé ».

## Écarté volontairement

Publication automatique sur YouTube (exige un compte OAuth), avatars et
voix IA à l'excès, effets sonores, télémétrie.
