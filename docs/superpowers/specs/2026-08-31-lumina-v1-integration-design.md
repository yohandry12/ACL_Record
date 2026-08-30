# Design — Lumina Recorder v1 : intégration des modules IA

**Date** : 2026-08-31
**Statut** : validé (brainstorming avec l'utilisateur)
**Portée** : LuminaRecorder/ uniquement (le prototype racine n'est pas modifié)

## Objectif

Livrer une v1 solide et installable : enregistrement d'écran fiable + les modules IA
existants (Privacy Blur, Clean Canvas, Overlay système, sous-titres Whisper, Magic Cut)
enfin branchés dans l'interface. Les nouveautés (streaming cloud, assistant vocal,
miniatures IA) attendent la v2.

## Décisions de cadrage

- **Cible** : produit distribuable (utilisateurs lambda + informaticiens). Fiabilité
  et simplicité d'installation priment.
- **Cloud** : aucun serveur hébergé par Lumina. En v2, l'utilisateur branchera son
  propre stockage (Drive, S3…). Rien en v1.
- **Approche retenue** : chaîne de filtres temps réel + post-traitement (approche 2),
  préférée au tout-post-traitement (pas de confidentialité réelle) et au système de
  plugins complet (sur-ingénierie pour 5 modules connus).

## Problème de fondation corrigé en premier

`RecorderCore` stocke actuellement toutes les frames en RAM (`self.frames.append`)
et n'écrit qu'à l'arrêt. À 1080p/30fps ≈ 11 Go de RAM par minute → crash en ~30 s
sur une machine à 8 Go. **Correction : ouvrir le `VideoWriter` au démarrage et écrire
chaque frame immédiatement après filtrage.** Mémoire constante quelle que soit la durée.

## Architecture

Deux nouveaux dossiers. Les moteurs existants (`ai/`, `services/`) restent intacts :
on les enveloppe (adaptateurs), on ne les réécrit pas. Leurs blocs `__main__` de test
continuent de fonctionner.

```
LuminaRecorder/src/
├── core/
│   ├── recorder_core.py      # MODIFIÉ : écriture disque en continu + chaîne de filtres
│   ├── encoder.py            # inchangé
│   └── system_analyzer.py    # inchangé
├── filters/                  # NOUVEAU — filtres temps réel (frame par frame)
│   ├── base.py               # FrameFilter : interface commune
│   ├── privacy_blur_filter.py    # enveloppe PrivacyBlurService
│   ├── clean_canvas_filter.py    # enveloppe CleanCanvasEngine
│   └── overlay_filter.py         # enveloppe SystemOverlayService
├── postprocess/              # NOUVEAU — traitement après arrêt
│   ├── base.py               # PostProcessor : interface commune
│   ├── subtitles_processor.py    # enveloppe WhisperTranscriber → .srt
│   └── magic_cut_processor.py    # enveloppe MagicCutEngine → coupes réelles FFmpeg
├── ai/                       # moteurs existants, inchangés
├── services/                 # moteurs existants, inchangés
├── ui/                       # MODIFIÉ : carte "Options IA" (5 cases à cocher)
└── utils/                    # config : persistance des choix dans [ai] du .ini
```

### Interfaces centrales

```python
class FrameFilter:                        # filters/base.py
    name: str
    enabled: bool
    def process(self, frame: np.ndarray) -> np.ndarray: ...

class PostProcessor:                      # postprocess/base.py
    name: str
    def run(self, video_path: str, audio_path: str,
            progress_cb: Callable[[float], None]) -> PostProcessResult: ...
```

`PostProcessResult` : succès/échec, chemin du fichier produit, message d'erreur éventuel.

Extensibilité v2 : miniature IA = un `PostProcessor` de plus ; assistant vocal = un
contrôleur qui appelle start/stop ; Smart Focus (v2, exclu de la v1 car sa détection
de fenêtre active est simulée) = source de crop branchée sur la boucle de capture.

## Flux de données

### Pendant l'enregistrement

```
grab écran (mss) → BGR → [filtres cochés, en série] → VideoWriter.write()
```

- Plus de buffer RAM. Écriture disque frame par frame.
- Audio inchangé (chunks WAV légers, gain numpy déjà en place).

### Garde-fou performance

- Budget par frame = 1/fps (33 ms à 30 fps). Temps de chaque filtre mesuré.
- Un filtre qui dépasse son budget sur 30 frames consécutives (~1 s) est désactivé
  automatiquement, message dans la barre de statut
  (« ⚠ Clean Canvas désactivé (machine trop lente) »). L'enregistrement continue.

### À l'arrêt

```
stop → VideoWriter.release + WAV sauvé
     → FFmpeg : fusion audio/vidéo + bitrate + gain (existant)
     → post-processeurs cochés, en série, dans un thread :
          1. Sous-titres : Whisper sur le WAV → Lumina_XXX.srt à côté du .mp4
          2. Magic Cut   : silences sur WAV → coupes FFmpeg → Lumina_XXX_cut.mp4
     → fenêtre de progression (barre + étape en cours), UI jamais gelée
```

- Ordre fixe : sous-titres AVANT Magic Cut (timestamps alignés sur la vidéo originale).
- Chaque résultat = fichier séparé. L'enregistrement brut n'est jamais écrasé.
- Magic Cut : le moteur actuel ne produit qu'une EDL. Le processeur ajoute
  l'application réelle des coupes via FFmpeg (segments `get_trimmed_segments()` →
  découpe/concat). Seul vrai développement nouveau ; le reste est du câblage.

## Interface utilisateur

Nouvelle carte « 🤖 Options IA » à côté des 3 cartes existantes :

| Case | Type | Défaut |
|------|------|--------|
| Flou confidentialité | filtre temps réel | off |
| Masquer notifications | filtre temps réel | off |
| Overlay métriques | filtre temps réel | off |
| Sous-titres auto | post-traitement | off |
| Couper les silences | post-traitement | off |

- Tout désactivé par défaut : l'utilisateur lambda garde un enregistreur simple.
- Choix persistés dans la section `[ai]` du fichier .ini (via `ConfigManager`),
  restaurés au lancement.
- Whisper absent → case « Sous-titres » grisée, info-bulle « pip install faster-whisper ».

## Gestion d'erreurs

Règle d'or : **on ne perd jamais un enregistrement**.

- Filtre qui lève une exception → désactivé à chaud, capture continue, message statut.
- Post-processeur qui échoue → passage au suivant, .mp4 original intact, résumé final
  (« ✓ Vidéo OK · ✗ Sous-titres échoués (raison) »).
- FFmpeg introuvable → détecté AVANT le démarrage de l'enregistrement.

## Tests (`tests/`, pytest)

- Unitaires filtres : frame synthétique → zone floutée / overlay présent / dimensions
  intactes.
- Unitaire garde-fou : filtre volontairement lent → désactivation après 30 frames.
- Unitaire Magic Cut FFmpeg : WAV synthétique à silences connus (générateur déjà dans
  `magic_cut.py`) → durée du fichier coupé vérifiée.
- Intégration : enregistrement réel de 2 s sans puis avec filtres → .mp4 valide,
  lisible par cv2.

## Hors périmètre v1 (acté)

Streaming cloud (v2 : l'utilisateur branche son propre stockage), assistant vocal,
miniatures IA, Smart Focus (v2 avec vraie détection win32gui), CLI réelle,
CustomTkinter.
