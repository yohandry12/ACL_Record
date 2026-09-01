# Écrire un plugin Lumina

Un plugin est **un seul fichier Python** que vous déposez dans un
dossier. Pas d'installation, pas de compilation, pas de compte à créer.

Ces trois exemples sont testés à chaque modification de Lumina : s'ils
cessaient de fonctionner, la suite de tests échouerait. Vous pouvez donc
les copier sans crainte qu'ils décrivent un contrat périmé.

## Démarrer en trois minutes

1. Copiez `filigrane.py` dans le dossier des plugins :

   ```
   %LOCALAPPDATA%\LuminaRecorder\plugins\
   ```

   Le bouton **Extensions** de Lumina ouvre ce dossier pour vous
   (« Ouvrir le dossier »).

2. Ouvrez le panneau **Extensions** : votre plugin y apparaît.
3. Activez son interrupteur. Il s'appliquera au prochain enregistrement.

## Le bloc d'identité

Chaque plugin déclare un dictionnaire nommé `LUMINA_PLUGIN`, en haut du
fichier :

```python
LUMINA_PLUGIN = {
    'nom': 'Filigrane',
    'description': 'Incruste un texte dans le coin de la vidéo',
    'auteur': 'Votre nom',
    'version': '1.0',
    'api': 1,
}
```

**Ce bloc est lu sans exécuter votre fichier.** Lumina l'analyse
syntaxiquement : aucune ligne de votre code ne tourne tant que
l'utilisateur n'a pas activé le plugin lui-même. C'est ce qui permet
d'afficher un plugin inconnu dans la liste sans lui faire confiance.

Conséquence pratique : gardez ce bloc littéral. Une valeur calculée
(`'version': lire_version()`) rend le plugin illisible, donc invisible.

Le champ `api` est la version du contrat pour laquelle vous écrivez.
La version actuelle est **1**. Un plugin qui déclare un numéro plus
élevé n'est pas chargé : il apparaît dans la liste avec la raison
affichée, plutôt que de planter en pleine capture.

## Les deux contrats

Votre fichier doit exposer une classe nommée exactement `Plugin`, qui
hérite de l'un des deux :

### `FrameFilter` — pendant l'enregistrement

Appelé pour **chaque image capturée**. Voir `filigrane.py` (le plus
simple) et `horodatage.py` (avec un état conservé entre les images).

```python
from filters.base import FrameFilter

class Plugin(FrameFilter):
    name = "Mon filtre"

    def process(self, frame):
        # frame : tableau numpy BGR
        return frame   # mêmes dimensions, même type
```

Trois règles :

- **Retournez une image de mêmes dimensions et même type.** L'encodeur
  attend un flux régulier.
- **Restez sous le budget.** À 30 images/s, vous disposez d'environ
  33 ms par image, tous filtres confondus. Un filtre qui dépasse ce
  budget sur 30 images consécutives est désactivé à chaud, et
  l'enregistrement continue sans lui.
- **Faites le travail coûteux dans `__init__`.** Il s'exécute une fois ;
  `process` s'exécute des milliers de fois.

### `PostProcessor` — après l'enregistrement

Appelé une fois, sur le fichier terminé. Voir `gif.py`.

```python
from postprocess.base import PostProcessor, PostProcessResult

class Plugin(PostProcessor):
    name = "Mon traitement"

    def run(self, video_path, audio_path, progress_cb):
        progress_cb(0.5)          # avancement, entre 0.0 et 1.0
        return PostProcessResult(name=self.name, success=True,
                                 output_path=chemin_produit)
```

Deux règles :

- **Ne levez jamais d'exception.** Retournez
  `PostProcessResult(success=False, error="…")`. Une exception ferait
  perdre les résultats des traitements suivants.
- **Écrivez à côté, jamais par-dessus.** Le fichier d'origine de
  l'utilisateur ne doit courir aucun risque.

## Ce que Lumina garantit

- **Lister n'exécute rien.** Vous pouvez inspecter un plugin reçu d'un
  tiers dans l'interface avant de décider de l'activer.
- **Un plugin défectueux est ignoré.** Erreur de syntaxe, exception à
  l'import, classe `Plugin` absente : le plugin est simplement absent,
  l'application démarre normalement.
- **Un plugin lent est désactivé, pas subi.** L'enregistrement continue.
- **Rien n'est installé à votre insu.** Lumina ne télécharge aucun
  plugin : vous seul déposez des fichiers dans ce dossier.

## Ce que Lumina ne garantit pas

Un plugin que vous activez est **du code Python qui tourne avec vos
droits**. Il peut lire vos fichiers et accéder au réseau. Lumina l'isole
des pannes, pas des intentions.

N'activez que des plugins dont vous connaissez l'origine — et comme ce
sont de simples fichiers texte, vous pouvez toujours les ouvrir et les
lire avant.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| Le plugin n'apparaît pas | `LUMINA_PLUGIN` absent, non littéral, ou nom de fichier commençant par `_` |
| Affiché avec une erreur | Champ `api` supérieur à la version gérée, ou absent |
| Activé mais sans effet | Classe non nommée `Plugin`, ou n'héritant d'aucun des deux contrats |
| Se désactive pendant la capture | Budget temps réel dépassé, ou exception levée dans `process` |
