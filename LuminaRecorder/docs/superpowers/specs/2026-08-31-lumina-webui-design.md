# Lumina — Interface web (PyWebView) : conception

**Date :** 2026-08-31
**Statut :** validé, prêt pour le plan d'implémentation

## Objectif

Remplacer l'interface tkinter par une interface HTML/CSS rendue dans
PyWebView, avec une direction visuelle « studio professionnel sombre » et
des animations ciblées. Le moteur d'enregistrement ne change pas.

## Pourquoi PyWebView

tkinter ne permet ni coins arrondis, ni ombres, ni transparence par
widget, ni animation fluide. Ces limites sont structurelles, pas
contournables. WebView2 (vérifié sur la machine cible : Chromium 151)
donne accès à `backdrop-filter`, aux animations composées et aux polices
variables — vérifié par test réel avant d'écrire cette spec, de même que
le pont bidirectionnel Python↔JS.

Coût assumé : la couche UI est réécrite (961 lignes de tkinter). Le
moteur (`core/`, `filters/`, `postprocess/`, `services/`) n'est pas
touché.

## Direction visuelle

**Studio professionnel sombre.** Référence : DaVinci Resolve, Ableton
Live. Le choix se justifie par l'usage : Lumina s'ouvre tous les jours,
et un thème néon fatigue là où un gris neutre reste lisible.

### Palette

| Rôle | Valeur | Usage |
|---|---|---|
| `--bg-base` | `#131417` | Fond de fenêtre |
| `--bg-panel` | `#1A1C20` | Panneaux de réglages |
| `--bg-elevated` | `#22252A` | Champs, contrôles |
| `--border` | `#2E3238` | Séparations |
| `--text` | `#E8EAED` | Texte principal |
| `--text-dim` | `#9AA0A6` | Libellés secondaires |
| `--accent` | `#F59E0B` | Accent unique (ambre) |
| `--rec` | `#EF4444` | Enregistrement en cours |
| `--ok` | `#34D399` | Succès |

Un seul accent chaud. Pas de second dégradé décoratif : la couleur ne
sert qu'à distinguer l'action principale et l'état d'enregistrement.

### Typographie

`Inter` en police variable si présente, sinon `Segoe UI Variable`, sinon
`system-ui`. Chiffres du chronomètre en `font-variant-numeric:
tabular-nums` — sans quoi le compteur tressaute à chaque seconde.

Aucune police n'est téléchargée : l'application doit fonctionner hors
ligne. On se limite aux polices présentes sur Windows.

### Composition

L'écran cible mesure 1366×768 (mesuré sur la machine de l'utilisateur).
La composition doit donc être dense sans être serrée : pas de grands
vides façon page d'accueil.

```
┌──────────────────────────────────────────────┐
│ LUMINA                            ─ □ ✕      │  barre de titre propre
├──────────────────────────────────────────────┤
│                                              │
│            ⏺  COMMENCER                      │  action principale
│         F9 · 00:00:00                        │
│                                              │
├───────────┬───────────┬──────────────────────┤
│  VIDÉO    │  AUDIO    │  IA                  │  3 colonnes
│  ...      │  ...      │  ...                 │
└───────────┴───────────┴──────────────────────┘
```

## Animations

**Généreuses mais ciblées** : chaque animation communique un état. Rien
ne tourne en boucle sans raison.

| Moment | Animation | Durée |
|---|---|---|
| Ouverture | Panneaux qui montent en cascade, 60 ms d'écart | 400 ms |
| Survol | Élévation + éclaircissement du bord | 150 ms |
| Clic | Léger enfoncement | 80 ms |
| Enregistrement | Pulsation lente du bouton + point rouge | 2 s, en boucle |
| Chronomètre | Chiffres qui glissent verticalement | 200 ms |
| Traitement | Barre de progression + étape nommée | continu |

Contrainte : n'animer que `transform` et `opacity`, jamais `width`,
`height` ou `top` — ces dernières déclenchent un recalcul de mise en page
à chaque image et saccadent.

`prefers-reduced-motion` désactive tout sauf les changements d'état
instantanés. Ce n'est pas une option : certains utilisateurs ont des
troubles vestibulaires.

## Architecture

### Découpage

```
src/
  webui/
    __init__.py
    app.py           Fenêtre PyWebView, cycle de vie
    bridge.py        Classe exposée au JS (js_api)
    state.py         État applicatif sérialisable
    assets/
      index.html
      style.css
      app.js
  ui/
    main_window.py   Ancienne interface, conservée
  core/
    ai_options.py    EXTRAIT de main_window.py (voir plus bas)
```

### Extraction préalable : `AIOptions`

`AIOptions` vit aujourd'hui dans `src/ui/main_window.py` alors que c'est
du code métier : elle lit la configuration et construit les filtres et
post-processeurs. Les deux interfaces doivent la partager, sinon la
logique serait dupliquée et divergerait.

Elle part dans `src/core/ai_options.py`, sans changement de comportement.
`main_window.py` l'importe depuis son nouvel emplacement. C'est la
première tâche du plan, et elle est vérifiable par les tests existants
(`test_ai_options_config.py`).

### Le pont Python↔JS

Une seule classe `LuminaBridge` exposée en `js_api`. Elle ne contient
aucune logique : elle traduit les appels JS vers le moteur existant.

Méthodes appelées par le JS :

| Méthode | Retour | Rôle |
|---|---|---|
| `get_initial_state()` | dict | Réglages, périphériques, disponibilité des fonctions IA |
| `start_recording()` | dict | Démarre ; renvoie succès ou message d'erreur |
| `stop_recording()` | dict | Arrête, encode, lance le post-traitement |
| `set_option(clé, valeur)` | dict | Modifie et persiste un réglage |
| `choose_folder()` | str | Ouvre le sélecteur de dossier natif |
| `open_output_folder()` | None | Ouvre l'explorateur sur le résultat |

Événements poussés du Python vers le JS (`window.evaluate_js`) :

| Événement | Charge utile |
|---|---|
| `tick` | secondes écoulées |
| `state` | `idle` / `pending` / `recording` / `processing` |
| `progress` | étape, avancement 0–1 |
| `error` | message lisible |
| `done` | chemin du fichier, résultats du post-traitement |

**Règle absolue :** tout appel au moteur qui peut durer (encodage,
post-traitement) part dans un thread. Le fil de PyWebView ne doit jamais
être bloqué, sinon la fenêtre gèle — le même piège que `root.after` en
tkinter, avec les mêmes conséquences.

Symétriquement, `window.evaluate_js` est appelé depuis des threads de
travail : la classe pont sérialise ses envois pour éviter que deux
threads écrivent en même temps dans la vue.

### Barre flottante pendant l'enregistrement

Au démarrage, la fenêtre principale se transforme en une barre compacte
(environ 320×56) posée en haut à droite, sans bordure et toujours
au-dessus.

Justification : la fenêtre pleine occupe l'écran que l'on filme, et la
réduire complètement priverait l'utilisateur de tout retour visuel. La
barre montre le temps écoulé et le bouton d'arrêt, sans gêner.

Réalisation : `window.resize()` + `window.move()` + `on_top`, et une
classe CSS `body.compact` qui masque tout sauf la barre. Pas de seconde
fenêtre — deux fenêtres poseraient un problème de synchronisation d'état
pour un gain nul.

Au retour à l'état de repos, la fenêtre reprend sa taille et sa position
d'origine, mémorisées avant la bascule.

### Migration

L'interface web devient celle par défaut. L'ancienne reste accessible :

```
python main.py             → interface web
python main.py --classic   → interface tkinter
```

L'ancienne sera retirée une fois la nouvelle éprouvée à l'usage. En
attendant, un défaut bloquant de la nouvelle interface ne laisse
personne sans application utilisable.

## Gestion des erreurs

Chaque échec doit être visible et compréhensible, jamais silencieux :

- **WebView2 absent** — l'interface web ne peut pas démarrer. On bascule
  automatiquement sur tkinter en expliquant pourquoi, plutôt que de
  planter. (WebView2 est présent sur Windows 11 et sur la plupart des
  Windows 10 à jour, mais pas garanti.)
- **Fonctions IA indisponibles** — la case est désactivée et porte le nom
  du paquet à installer, comme aujourd'hui. Aucune fonction n'est jamais
  simulée.
- **Exception dans le pont** — attrapée, journalisée, renvoyée au JS sous
  forme de message lisible. Une erreur d'affichage ne doit pas arrêter un
  enregistrement en cours.

## Tests

Le pont est du code Python testable sans interface : `LuminaBridge` reçoit
son moteur par injection, donc les tests l'appellent avec un faux moteur
et vérifient les valeurs de retour et les transitions d'état.

- `test_bridge.py` — chaque méthode, y compris les cas d'erreur
- `test_ai_options.py` — inchangé, doit passer après l'extraction
- La suite existante (147 tests) doit rester verte

Ce qui n'est pas testable automatiquement (rendu, animations, ressenti)
est vérifié par capture d'écran, comme pour les corrections précédentes.

## Hors périmètre

- Aucun changement du moteur d'enregistrement
- Aucun changement des filtres ni des post-processeurs
- L'assistant vocal reste écarté (raccourci global déjà en place)
- Pas de thème clair pour l'instant : les variables CSS le rendront
  possible plus tard sans réécriture
