# Curseur et halo de clic — design

Date : 14 septembre 2026. Premier sujet de la feuille de route
`2026-09-14-feuille-de-route.md`.

## Problème

`mss` ne capture pas le pointeur de la souris. Rien dans Lumina ne le
dessine : la clé `[recording] cursor_visible = true` de
`config/default_config.ini` n'est lue nulle part. Toute vidéo produite
par Lumina est donc sans pointeur, ce qui rend un tutoriel difficile à
suivre.

## Objectif

Dessiner le pointeur dans la vidéo, et un halo discret à chaque clic,
sans hook système et sans nouvelle dépendance.

## Architecture

Un filtre temps réel `CursorFilter` (`src/filters/cursor_filter.py`),
inséré dans la chaîne existante (`filters/base.py::FilterChain`). Il
bénéficie ainsi du budget par image et de la désactivation à chaud.

Ordre de la chaîne, construit par `AIOptions.build_filters` :

1. filtres natifs existants : flou de confidentialité, Clean Canvas,
   overlay système ;
2. **curseur** (nouveau) ;
3. plugins de l'utilisateur ;
4. webcam.

Le curseur vient après les filtres natifs pour ne pas être flouté par
l'OCR ni masqué par Clean Canvas, et avant la webcam pour que la
vignette reste au-dessus.

## Composants

### `cursor_filter.py`

- `cursor_is_available() -> bool` : `os.name == 'nt'`. Hors Windows,
  l'option est grisée et le filtre n'est pas construit, même règle que
  `ocr_is_available`.
- `SondeWin32` : lecture de l'état du pointeur par **ctypes uniquement**
  (`user32.GetCursorPos`, `GetCursorInfo`, `GetAsyncKeyState`,
  `LoadCursorW`). Pas de hook `WH_MOUSE_LL`, pour la même raison que
  `global_hotkey.py` préfère `RegisterHotKey` : pas de privilège, pas
  de comportement suspect pour un antivirus. Interface :
  - `position() -> (x, y)` en pixels physiques (le processus est
    DPI-aware via `enable_dpi_awareness`, donc les mêmes pixels que la
    région mss) ;
  - `forme() -> 'fleche' | 'texte' | 'main' | None` : `None` si le
    système masque le pointeur (`CURSOR_SHOWING` absent, par exemple
    pendant la saisie ou une vidéo plein écran). La forme vient de
    `GetCursorInfo().hCursor` comparé aux handles de
    `LoadCursorW(None, IDC_ARROW | IDC_IBEAM | IDC_HAND)` ; tout autre
    handle donne `'fleche'` ;
  - `bouton_presse() -> bool` : `GetAsyncKeyState(VK_LBUTTON)` ou
    `VK_RBUTTON`, bit 0x8000.
- `CursorFilter(region_provider, halo=True, sonde=None)` :
  - `region_provider: Callable[[], Optional[dict]]` renvoie la région
    mss (`left`, `top`, `width`, `height`) de l'image en cours ; `None`
    → image rendue telle quelle ;
  - `sonde` par défaut `SondeWin32` ; les tests injectent une sonde
    factice, aucun test ne touche Win32 ;
  - `process(frame)` : lit la sonde une fois, calcule la position dans
    l'image `(x - left, y - top)`, dessine le pointeur si la forme n'est
    pas `None` et si la position est dans l'image, met à jour et dessine
    les halos, retourne l'image (même forme, même dtype). Toute
    exception de la sonde → image inchangée, jamais d'exception.

### Dessin du pointeur

Vectoriel avec cv2, pas la bitmap Windows (indépendant du thème, net à
toute résolution). Trois formes : flèche, barre de texte, main. Blanc,
contour noir 1 px, `LINE_AA`. Hauteur de base 19 px (flèche Windows à
100 %), multipliée par `echelle = clamp(hauteur_image / 1080, 1, 2)`.
Le point chaud (pointe de la flèche, milieu de la barre, index de la
main) est placé sur la position lue.

Le filtre travaille **avant** le `cv2.resize` de `_write_frame`, donc le
pointeur suit la mise à l'échelle de la vidéo finale.

### Halo de clic

- Déclenché sur **front montant** de `bouton_presse()` : un bouton
  maintenu ne produit qu'un halo. Gauche et droit produisent le même
  halo.
- Anneau ambre `(11, 158, 245)` BGR (l'ambre de la vignette webcam),
  épaisseur 3, rayon de 8 à 28 px × échelle sur 0,4 s, opacité de 0,9 à
  0. Composé par `cv2.addWeighted` sur la seule ROI englobante de
  l'anneau, rognée aux bords de l'image.
- Plusieurs halos peuvent coexister (double-clic) ; la liste est purgée
  à l'expiration. Le halo continue jusqu'au bout même si le pointeur
  sort de l'image ou est masqué ensuite.
- Le temps vient de `time.monotonic()` ; les tests le remplacent.
- Limitation acceptée : la détection se fait par sondage à chaque image
  (30 fois par seconde), un clic plus court qu'une image peut être
  manqué.

### `RecorderCore`

Nouvel attribut `capture_region: Optional[dict]`, `None` à la
construction, affecté avec la région juste avant `sct.grab` dans la
boucle de capture (`recorder_core.py`, autour de la ligne 556). C'est la
seule modification du cœur. Le pont fournit
`lambda: recorder.capture_region` comme `region_provider`.

### `AIOptions.build_filters`

Nouveau paramètre `cursor_filter=None`, inséré entre les filtres natifs
et les plugins. Aucune autre logique.

## Réglages

| Clé .ini | Défaut | Rôle |
|---|---|---|
| `[recording] cursor_visible` | `true` (existe déjà) | dessine le pointeur |
| `[recording] click_halo` | `true` (nouvelle) | dessine le halo de clic |

Les deux défauts sont « on » : le pointeur est un correctif, le halo est
discret, et c'est ce qu'attend le public visé. Un halo sans pointeur est
sans objet : quand `cursor_visible` est faux, aucun filtre n'est construit
et `click_halo` est ignoré.

Pont (`bridge.py`) :

- `SIMPLE_KEYS` += `'cursor_visible': ('recording', 'cursor_visible')`,
  `'click_halo': ('recording', 'click_halo')` ;
- `get_initial_state()['cursor'] = {'visible': bool, 'halo': bool,
  'available': cursor_is_available()}` ;
- au lancement, si `visible and cursor_is_available()` :
  `CursorFilter(lambda: recorder.capture_region, halo=click_halo)`
  passé à `AIOptions.build_filters(..., cursor_filter=...)`.

L'interface tkinter historique (`--classic`) partage `build_filters` mais
n'est pas câblée : hors périmètre.

## Interface (onglet Capture, après la ligne Smart Focus)

- Ligne « Curseur », sous-libellé « Pointeur dessiné dans la vidéo »,
  interrupteur `#cursor-visible`.
- Ligne « Halo de clic », sous-libellé « Cercle ambré à chaque clic »,
  interrupteur `#click-halo`, désactivé quand le curseur est décoché.
- `available` faux → les deux interrupteurs désactivés, sous-libellé
  « Windows uniquement ».
- Les deux ids entrent dans le contrat `tests/test_page_capsule.py`.
- Câblage dans `app.js` sur le modèle de `#smart-focus` (`set_option`
  immédiat, pas d'`innerHTML` avec des données du pont).

## Tests

`tests/test_cursor_filter.py`, avec une sonde factice et un temps
monkeypatché :

- pointeur dessiné à la position attendue pour chaque forme (au moins un
  pixel blanc au point chaud, image inchangée ailleurs) ;
- décalage de région : Smart Focus avec `left`/`top` non nuls, y compris
  négatifs (fenêtre maximisée) ;
- pointeur hors image → image identique ;
- forme `None` (masqué) → image identique ;
- front montant : bouton maintenu sur dix images → un seul halo ;
- deux clics rapprochés → deux halos ;
- halo expiré après 0,4 s → image identique ;
- halo près du bord → pas d'exception, image rognée ;
- `region_provider` renvoyant `None` → image identique ;
- sonde qui lève → image identique, pas d'exception ;
- `halo=False` → aucun halo malgré les clics ;
- performance : `process` sur une image 1920×1080 avec pointeur et un
  halo actif < 1 ms en moyenne sur 100 appels.

Autres :

- `tests/test_ai_options_config.py` : ordre natifs → curseur → plugins
  → webcam ; `cursor_filter=None` inchangé.
- Boucle de capture existante : `capture_region` reflète la région
  passée à `grab`.
- `tests/test_bridge.py` : clés `cursor_visible`/`click_halo` persistées ;
  état initial `cursor` ; filtre construit seulement si visible et
  disponible.
- `tests/test_page_capsule.py` : ids `cursor-visible`, `click-halo`.

## Vérification sur machine

Par l'utilisateur lui-même (règle : aucune capture d'écran lancée par
l'agent) : enregistrement de dix secondes avec clics, une fois avec
Smart Focus, une fois sans. Attendu : pointeur aux bonnes coordonnées et
de la bonne forme dans un champ texte, halo à chaque clic, aucun
pointeur quand la case est décochée.

## Hors périmètre

Journal de clics pour le zoom automatique (E2), bitmap réelle du
curseur, curseurs personnalisés, halo sur les touches du clavier, réglage
de couleur ou de taille du halo.
