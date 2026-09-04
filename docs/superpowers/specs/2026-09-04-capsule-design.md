# Refonte « capsule » : conception

**Date** : 4 septembre 2026
**Statut** : maquettes validées par l'utilisateur, implémentation lancée
**Maquettes** : canevas « Lumina Capsule » (quatre planches : repos,
décompte, feuille de réglages, widget). Les fichiers sources des
planches sont recopiés dans `docs/superpowers/maquettes/capsule/`.

## Le besoin

Rendre Lumina digne des meilleures applications macOS, sur Windows.
L'interface actuelle est un formulaire dans une fenêtre Windows :
barre de titre système, trois panneaux de réglages toujours visibles,
bouton d'enregistrement rectangulaire. Les références étudiées
(`assets/Records_examples/`) ont en commun : **un seul objet sombre**,
un chrono géant à chiffres tabulaires, une onde comme signature, des
boutons ronds à relief, un seul accent chaud.

## Décisions prises avec l'utilisateur

| Question | Décision |
|---|---|
| Périmètre | Capsule + widget + feuille de réglages (pas seulement le widget) |
| Méthode | Maquettes d'abord, validées, puis code |
| Bordure Windows | Retirée : la capsule est la fenêtre, sans cadre |
| Réglages | Derrière l'engrenage, dans une feuille qui glisse depuis la capsule |
| Webcam | Livrée en même temps (spec séparée, `2026-09-04-webcam-incrustation-design.md`) |
| Version | 1.5.0 pour les deux |

## Ce qui est prouvé sur cette machine

Mesuré avant de concevoir, pas supposé :

| Point | Résultat | Conséquence |
|---|---|---|
| Déplacer une fenêtre `frameless` | Fonctionne via la classe CSS `pywebview-drag-region` (pywebview capte mousedown/mousemove et appelle `pywebviewMoveWindow`) | `easy_drag=False`, zones de saisie explicites |
| `-webkit-app-region: drag` | Ignoré par WebView2 (propriété Electron) | Ne jamais s'en servir |
| Coins arrondis, Windows 10 | `SetWindowRgn(CreateRoundRectRgn(...))` fonctionne | À réappliquer après chaque `resize` |
| Coins arrondis, Windows 11 | `DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE=33, DWMWCP_ROUND=2)` | Une fois, à l'ouverture ; pas de région |
| Transparence par couleur clé | WebView2 l'ignore | Pas de marge transparente : la capsule EST la fenêtre, sans ombre portée extérieure |
| Exclusion de capture sur fenêtre sans cadre | `SetWindowDisplayAffinity(0x11)` fonctionne | Inchangé |
| Handle natif | `window.native.Handle.ToInt64()` | Déjà utilisé par `_set_capture_affinity` |

## Architecture

Une seule fenêtre PyWebView, sans cadre, qui change de taille selon
l'état. Toute la logique reste dans `LuminaBridge` ; la page ne fait
qu'afficher. Aucun changement au moteur de capture ni à l'encodage.

```
état      taille (px CSS)   contenu
idle      440 × 352         capsule : chrono, onde au repos, boutons, pastilles
pending   440 × 352         capsule : anneau de décompte
recording 360 × 180         widget : chrono, vignette webcam, bande d'onde
processing 440 × 352        capsule : chrono figé, progression à la place de l'onde
```

### 1. Fenêtre (`src/webui/app.py`, `src/webui/bridge.py`)

- `create_window(..., frameless=True, easy_drag=False, resizable=False,
  width=440, height=352, min_size=(360, 180), background_color='#0D0E11')`.
- `LuminaBridge.CAPSULE_SIZE = (440, 352)`, `COMPACT_SIZE = (360, 180)`.
  `full_size()` disparaît : la capsule a une taille fixe, elle tient sur
  1366×768 comme sur 4K.
- `_apply_window_mode` :
  - `PENDING` : rien ne bouge (le décompte se joue dans la capsule, là
    où l'utilisateur l'a posée), mais l'exclusion de capture est posée
    dès maintenant pour que la bascule suivante soit invisible.
  - `RECORDING` : mémoriser la position, `on_top = True`, `resize(360, 180)`,
    `move` vers le coin haut droit (marge 24 px), coins réappliqués.
  - `IDLE` / `PROCESSING` : `on_top = False`, exclusion retirée,
    `resize(440, 352)`, retour à la position mémorisée, coins réappliqués.
  - `_set_native_frame` est supprimée : il n'y a plus de bordure à
    retirer ni à rendre.
- `_arrondir_coins()` : nouvelle méthode. Windows 11 (build ≥ 22000) →
  attribut DWM une seule fois ; sinon `SetWindowRgn` avec un rayon de
  28 px (capsule) ou 22 px (widget). Échec toléré, comme l'affinité.
- `minimize()` et `close()` existent déjà : la page les appelle depuis
  ses propres boutons.
- Annulation du décompte : `stop_recording()` en état `PENDING` rend
  déjà `{'cancelled': True}` ; la page l'appelle sur Échap.

### 2. Page (`src/webui/assets/index.html`, `style.css`, `app.js`)

Réécriture de la page. `shards.js` est supprimé : la capsule est un
objet opaque, un fond animé n'a plus de surface où vivre et coûtait des
cycles.

**Capsule au repos** (planche « Capsule · repos ») :
- En-tête : point ambre + LUMINA à gauche ; à droite, deux boutons
  ronds de 28 px (Extensions, Réglages) **puis deux boutons de 24 px
  ajoutés à la maquette : Réduire (—) et Fermer (✕)** — une fenêtre
  sans cadre n'a plus ceux de Windows. Tout l'en-tête hors boutons est
  zone de saisie (`pywebview-drag-region`).
- Chrono 72 px, `Segoe UI Variable Display` 300, `tabular-nums`,
  `00:00` gris au repos. Sous lui : statut (« Prêt à enregistrer »,
  erreurs, avis) et puce du raccourci (F9). Le bloc chrono est aussi
  zone de saisie.
- Onde au repos : 60 points de 2 px, gris `#3D424A`. Pendant le
  traitement, la même zone accueille la barre de progression et le nom
  de l'étape.
- Trois boutons ronds : Dossier (46 px, `open_output_folder`), REC
  (68 px ambre, `toggle_recording`), Smart Focus (46 px, bascule
  `set_option('smart_focus')`, allumé en ambre quand actif, grisé avec
  infobulle « Nécessite pywin32 » si indisponible).
- Pastilles Micro / Son système / Webcam : bascules `set_option`
  (`mic_enabled`, `system_audio`, `webcam_enabled`), allumées
  (`on`) ou éteintes (`off`), grisées avec la raison quand la fonction
  est indisponible (aucun micro, PyAudioWPatch absent, aucune webcam).
- Résultat d'un enregistrement : statut « Enregistrement terminé ·
  Ouvrir », « Ouvrir » cliquable (`open_output_folder`). Les échecs de
  post-traitement s'affichent dans le statut, en rouge, sans
  disparaître.

**Décompte** (planche « Capsule · décompte ») : anneau ambre de 132 px
autour du chiffre (84 px), « La capture commence », « Échap pour
annuler » en en-tête, pied : état de la webcam (« Webcam prête » /
« Webcam indisponible ») et « 1280×720 · 30 im/s · MP4 ».

**Widget** (planche « Widget · enregistrement + webcam ») : colonne
gauche (● Enregistrement, chrono 44 px `mm:ss` avec les **heures** en
exposant comme aujourd'hui — la maquette montre « 26 » à cette place,
c'est « 1h » qui s'y affiche —, `MP4 · 1280×720 · ≈ 45 Mo`), vignette
webcam 84 px à droite (absente si webcam inactive, la colonne gauche
s'étend), bande d'onde ambre de 44 px avec Pause (visuel seulement,
grisé, infobulle « Bientôt ») et Arrêt. Le rang du haut est zone de
saisie. L'onde reste ce qu'elle est aujourd'hui : un rythme visuel, pas
une mesure du micro.

**Feuille de réglages** (planche « Feuille de réglages · Webcam ») :
glisse depuis le bas de la capsule, laisse voir l'en-tête à 45 %.
Poignée, titre « Réglages », onglets Capture / Audio / Webcam / IA.
Corps défilant (`overflow-y: auto`, barre fine) — la capsule ne grandit
jamais. Contrôles : interrupteurs à glissière, listes, contrôles
segmentés, grille de coins. Un changement est persisté aussitôt par
`set_option`, comme aujourd'hui.

| Onglet | Contenu (tout existe déjà, sauf Webcam) |
|---|---|
| Capture | Résolution, Débit, Smart Focus, Dossier de sortie, Raccourci (lecture) |
| Audio | Microphone + liste, Son système, Volume d'entrée |
| Webcam | Voir la spec webcam : Incruster, Caméra, Forme, Coin, Taille, Miroir, Tester |
| IA | Fournisseur (ligne + bouton « Configurer… » → sous-feuille), avertissement de charge, les huit cases IA, seuil Magic Cut, Supprimer l'original |

**Autres feuilles**, même mécanique, empilables (une sous-feuille glisse
par-dessus la feuille ouverte) :
- **Extensions** (bouton de l'en-tête) : contenu actuel de la modale
  Extensions, inchangé.
- **Fournisseur IA** (depuis l'onglet IA) : contenu actuel de la modale.
- **Mise à jour** : quand `update_available` arrive, une pastille ambre
  « 1.6.0 disponible » apparaît dans l'en-tête, à gauche des boutons ;
  clic → feuille avec notes, progression, Installer / Plus tard.
- La version installée s'affiche en pied de la feuille de réglages.

Échap ferme la feuille du dessus ; sans feuille ouverte, Échap annule
le décompte (`pending`) ou arrête l'enregistrement (`recording`).

**Mouvement** : ouverture de feuille 260 ms, fermeture 200 ms, courbe
`linear()` échantillonnée d'un ressort sans dépassement ; boutons ronds
`scale(0.96)` au `:active`. `prefers-reduced-motion` : les feuilles
apparaissent sans glissement.

### 3. Pont : API vue par la page

Inchangé sauf :

| Ajout | Rôle |
|---|---|
| `set_option('webcam_enabled', bool)` et les clés `webcam_*` | Spec webcam |
| `get_webcams()`, `test_webcam(index)` | Spec webcam |
| `get_initial_state()['webcam']` | `{enabled, device, forme, coin, taille, miroir, available, devices}` |
| événement `webcam_preview` | Spec webcam |

Supprimé : rien. `minimize`, `close`, `open_output_folder`,
`choose_folder`, `get_extensions`, `install_extension`, `get_plugins`,
`set_plugin_actif`, `open_plugins_folder`, `get_ai_config`,
`set_ai_provider`, `set_ai_key`, `test_ai_provider`, `check_charge`,
`install_update` gardent leur signature : la page change, pas le pont.

## Ce qui ne change pas

- Le moteur (`recorder_core`, filtres, encodeur, post-traitements).
- Le raccourci global et son comportement.
- Les jetons de couleur (`--accent oklch(76.9% 0.166 70.1)`, `--rec`,
  `--ok`, gris `#0D0E11 / #1A1C20 / #22252A / #2E3238`), la police
  `Segoe UI Variable`.
- L'interface classique tkinter (`--classic`) : intouchée, toujours
  le repli si WebView2 manque.
- Les tests existants du pont : ceux qui touchent `_set_native_frame`
  ou `full_size` sont adaptés, pas supprimés.

## Risques et parades

| Risque | Parade |
|---|---|
| `resize()` refusé quand `resizable=False` | **Sondé sur cette machine** : accepté, la fenêtre passe exactement à 360×180 |
| Taille de création fausse sur fenêtre sans cadre | **Sondé** : `width=440, height=352` donne 424×313 (pywebview retranche un cadre qui n'existe pas). Parade : `resize(*CAPSULE_SIZE)` dans `on_start`, qui donne l'exact |
| Région arrondie perdue après `resize` | `_arrondir_coins()` appelée après chaque `resize` ; **sondé** : `SetWindowRgn` rend 1 sur build 19045 |
| Écran à 125 / 150 % : tailles en px physiques | **Sondé** à 100 % : `window.width == innerWidth`, DPR 1. À d'autres échelles, mesurer `innerWidth` après `resize` et documenter |
| Fenêtre sans cadre = pas de Alt+Espace | Réduire et Fermer dans l'en-tête ; Alt+F4 fonctionne toujours |
| Feuille trop haute sur un onglet | Corps défilant, jamais de croissance de la fenêtre |

## Tests

`tests/test_bridge.py` — adaptations et ajouts :
- `CAPSULE_SIZE == (440, 352)`, `COMPACT_SIZE == (360, 180)`
- `pending` : pas de redimensionnement, affinité posée
- `recording` : `resize(360, 180)`, `on_top`, position mémorisée
- retour `idle` : `resize(440, 352)`, position rendue, affinité retirée
- `_arrondir_coins` appelée après chaque `resize` (fenêtre factice)
- `_arrondir_coins` ne lève jamais sans handle natif
- `get_initial_state()['webcam']` présent avec les six clés

`tests/test_page_capsule.py` — nouveau, sans navigateur : lit
`index.html` et vérifie la présence des identifiants que `app.js`
attend (chrono, statut, boutons rec/dossier/focus/réduire/fermer, les
trois pastilles, les quatre onglets, la vignette du widget) et
l'absence de `shards.js` et de toute référence à `-webkit-app-region`.

**Vérification manuelle obligatoire avant publication**, sur cette
machine : les quatre états à l'écran, déplacement par saisie, coins
arrondis, widget absent d'une capture, Échap pendant le décompte,
feuille ouverte sur chaque onglet.

## Publication

Version **1.5.0**, avec la webcam. Notes de version : « Nouvelle
interface capsule ; incrustation webcam ».
