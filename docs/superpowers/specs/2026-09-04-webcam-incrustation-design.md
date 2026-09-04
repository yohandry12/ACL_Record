# Incrustation webcam : conception

**Date** : 4 septembre 2026
**Statut** : validé avec l'utilisateur, en attente du plan d'implémentation

## Le besoin

Pour les tutoriels et les formations, montrer le visage du formateur
dans un coin de la vidéo enregistrée, découpé selon une forme (rond,
carré, carré arrondi). L'utilisateur doit se voir pendant qu'il
enregistre, pour se cadrer et vérifier son éclairage.

C'est ce que proposent Loom, OBS ou Screen Studio ; sans cela, Lumina
n'est pas comparé à eux. La fonction vit dans le socle — aucune
dépendance nouvelle, OpenCV lit déjà les webcams — et non dans une
extension téléchargeable qui la cacherait derrière un clic de plus.

## Décisions prises avec l'utilisateur

| Question | Décision |
|---|---|
| Se voir pendant l'enregistrement ? | Oui, vignette live dans le widget |
| Détourer le fond de la pièce ? | Non pour l'instant. Extension possible plus tard |
| Où vit la fonction ? | Socle, panneau Capture, à côté du micro |
| Disposition dans le widget | Vignette à droite du chrono, hauteur inchangée |

## Mesures qui contraignent la conception

Relevées sur la machine de développement (webcam intégrée, 640×480) :

| Mesure | Valeur | Conséquence |
|---|---|---|
| Ouverture de la webcam (MSMF) | 3,2 s | Ouvrir dès la construction du recorder, avant le décompte de 3 s |
| Un `read()` | 31 ms, bloquant | Jamais dans la boucle de capture : thread dédié |
| Cadence de lecture | 31,5 im/s | Suffisant, on ne garde que la dernière image |
| Budget de la boucle de capture | ~35 ms/image à 28 im/s | La composition doit rester sous 2 ms |

Le recorder et sa chaîne de filtres sont construits dans
`bridge.start_recording` (ligne ~608) **avant** que le thread du
décompte ne démarre (ligne ~641). L'ouverture de la webcam commence
donc pendant le décompte. Si elle n'est pas prête à la première image,
la vignette apparaît simplement quand elle l'est ; la capture ne
l'attend pas.

## Architecture

Trois unités, chacune testable seule :

```
WebcamSource (thread)  --dernière image-->  WebcamOverlayFilter  --> FilterChain
       |                                            |
       +--vignette JPEG 8 im/s--> bridge.emit('webcam_preview') --> widget
```

### 1. `src/core/webcam_source.py` — la source

```python
class WebcamSource:
    def __init__(self, device_index: int = 0, largeur: int = 640,
                 hauteur: int = 480): ...
    def start(self) -> None          # lance le thread, retourne aussitôt
    def latest(self) -> Optional[np.ndarray]   # dernière image BGR, ou None
    @property
    def erreur(self) -> str          # "" tant que tout va bien
    def stop(self) -> None           # libère la webcam (LED éteinte)

def lister_webcams() -> List[dict]   # [{'index': 0, 'nom': 'Integrated Webcam'}]
```

- Un thread lit en boucle avec `cv2.VideoCapture(index, cv2.CAP_MSMF)`
  et remplace la dernière image sous verrou. `latest()` ne bloque
  jamais.
- Si l'ouverture échoue (webcam prise par Teams, débranchée), `erreur`
  porte la cause lisible et `latest()` rend `None`. Une webcam qui
  meurt en cours de route produit le même état après trois lectures
  ratées consécutives.
- `lister_webcams()` obtient les noms par Windows
  (`Get-PnpDevice -Class Camera,Image`, ou WMI via `win32com` déjà
  présent) et les associe aux index OpenCV dans l'ordre. L'association
  n'est pas garantie par le système : le bouton **Tester** des réglages
  montre l'image de l'index choisi pour lever le doute. Sans nom
  disponible, l'entrée s'appelle « Webcam 0 ».

### 2. `src/filters/webcam_overlay_filter.py` — l'incrustation

```python
class WebcamOverlayFilter(FrameFilter):
    name = "Webcam"
    def __init__(self, source: WebcamSource, forme: str = "rond",
                 coin: str = "bas-droite", taille: str = "moyenne",
                 miroir: bool = True): ...
```

- **Formes** : `rond`, `carre_arrondi`, `carre`. Une forme est un masque
  alpha en niveaux de gris, calculé une fois par taille de vignette et
  mis en cache. Ajouter une forme, c'est ajouter une fonction qui
  dessine un masque.
- **Bordure et ombre** : bordure claire de 2 px (`oklch` de l'accent
  converti en BGR), ombre douce de 6 px sous la vignette. Le langage
  visuel de l'interface, dans la vidéo.
- **Coins** : `haut-gauche`, `haut-droite`, `bas-gauche`, `bas-droite`,
  marge de 2 % de la largeur.
- **Tailles** : `petite` 15 %, `moyenne` 22 %, `grande` 30 % de la
  hauteur de l'image capturée. La vignette est carrée ; l'image webcam
  4:3 est recadrée au centre.
- **Miroir** : activé par défaut, comme on se voit dans un miroir.
- **Ordre** : placé **en dernier** de la chaîne par `AIOptions.build_filters`,
  après le flou de confidentialité — sinon l'OCR flouterait le visage —
  et après les plugins.
- **Dégradation** : quand `source.latest()` rend `None`, le filtre
  retourne l'image telle quelle. La vignette disparaît de la vidéo ; le
  pont émet un avis (« Webcam perdue, enregistrement poursuivi sans
  elle ») une seule fois. L'enregistrement ne s'interrompt jamais pour
  une webcam.
- **Coût** : composition par `cv2.addWeighted` sur la seule zone de la
  vignette, masque précalculé. Cible mesurée : sous 2 ms pour une
  vignette de 200 px. Le garde-fou de `FilterChain` désactive le filtre
  s'il dépasse le budget 30 images de suite, comme tout autre filtre.

### 3. Réglages et interface

**Configuration** (`[webcam]` dans le `.ini`) :

```ini
[webcam]
enabled = false      ; JAMAIS activé sans choix explicite
device = 0
forme = rond
coin = bas-droite
taille = moyenne
miroir = true
```

**Panneau Capture**, sous la section Audio, nouvelle section **Webcam** :
interrupteur, liste des caméras par nom, forme (trois vignettes
cliquables), coin (quatre cases), taille (trois choix), miroir, bouton
**Tester** qui affiche 2 s d'image dans une bulle. Tout est grisé avec
la raison quand aucune webcam n'est détectée.

**Widget** : la vignette prend la place du poids et du format à droite
du chrono, 96 px, découpée selon la forme choisie. Elle est déjà exclue
de la vidéo comme tout le widget (`SetWindowDisplayAffinity`). Le pont
pousse `webcam_preview` avec un JPEG de 120 px encodé en base64, à
8 im/s, ~6 Ko par image, depuis le thread de la source. Sans webcam
active, le widget est strictement identique à aujourd'hui.

**Pont** : `get_webcams()`, `test_webcam(index)`, réglages via le
`set_option` existant. `start_recording` construit la source quand
`webcam.enabled` est vrai, la passe au filtre, et la ferme dans
`stop_recording` et sur toute sortie anormale.

## Ce qui ne change pas

- Le contrat `FrameFilter` et `FilterChain`.
- La synchronisation son/image : la webcam n'est pas un flux séparé,
  elle est composée dans chaque image au moment de sa capture. Aucun
  nouveau décalage possible.
- Le socle allégé : zéro dépendance ajoutée.

## Vie privée

- Désactivé par défaut, rien ne s'allume sans un geste de l'utilisateur.
- La webcam est libérée à l'arrêt : la LED s'éteint, preuve visible.
- Aucune image webcam n'est écrite ailleurs que dans la vidéo demandée.
- La vignette d'aperçu ne transite que du pont vers la page locale.

## Tests

`tests/test_webcam_source.py` — avec une fausse `cv2.VideoCapture` :
- `latest()` rend la dernière image, jamais une ancienne
- ouverture échouée → `erreur` renseignée, `latest()` `None`
- trois lectures ratées → même état, thread terminé
- `stop()` libère et arrête le thread
- test **optionnel** sur la vraie webcam (`pytest.skip` si absente) :
  une image arrive en moins de 5 s

`tests/test_webcam_overlay_filter.py` — sur images synthétiques :
- chaque forme produit le masque attendu (rond : coins transparents,
  centre opaque ; carré : tout opaque)
- chaque coin place la vignette au bon endroit, marge comprise
- chaque taille donne la bonne dimension
- miroir inverse l'image horizontalement
- source `None` → image inchangée, même identité mémoire
- bordure présente sur le pourtour
- coût mesuré sous 2 ms pour 200 px sur 1366×768

`tests/test_ai_options_config.py` — ajouts :
- le filtre webcam est dernier de la chaîne, après flou et plugins
- absent quand `webcam.enabled` est faux, même si une source existe

`tests/test_bridge.py` — ajouts :
- `get_webcams()` liste avec noms, jamais d'exception sans webcam
- la source est fermée à `stop_recording` et sur erreur de capture
- `webcam_preview` émis pendant l'enregistrement, jamais hors

## Publication

Version **1.5.0**. Première fonction visible ajoutée depuis la refonte
modulaire : elle en est la démonstration.
