# Lumina modulaire : alléger le socle, ouvrir aux plugins

Conception validée le 1er septembre 2026.

## Le problème

Lumina pèse **1,05 Go** installée. C'est un frein direct à l'adoption :
sur un poste ancien ou peu doté en stockage, l'application est écartée
avant d'avoir été essayée. L'objectif est qu'elle tourne sur toutes les
machines, des plus anciennes aux plus récentes, sans être volumineuse.

En parallèle, toute nouvelle fonctionnalité codée dans le cœur alourdit
ce cœur et le rend plus fragile. Un système de plugins résout ce second
problème — et par construction, il résout aussi le premier.

## L'idée directrice

**Un module optionnel et un plugin sont le même mécanisme** : du code
qui vit hors du programme principal, chargé dynamiquement au démarrage,
activable et désactivable.

On construit donc **un seul système**, utilisé pour deux usages :

| Usage | Origine | Exemple |
|---|---|---|
| Extension officielle | publiée par Lumina, installée depuis l'app | sous-titres locaux, OCR |
| Plugin | déposé par l'utilisateur dans un dossier | filigrane, conversion GIF |

Même chargeur, même dossier racine, même interrupteur dans l'interface.

## Où va le poids (mesuré)

| Composant | Poids | Utilité réelle |
|---|---|---|
| torch + torchvision | 377 Mo | OCR et sous-titres locaux |
| cv2 (OpenCV) | 190 Mo | écriture vidéo — **indispensable** |
| pyarrow | 76 Mo | **aucune — jamais importé, par rien** |
| av.libs | 63 Mo | dépendance déclarée de faster-whisper (`av>=11`) |
| ctranslate2 | 59 Mo | sous-titres Whisper |
| scipy, onnxruntime, pandas | 106 Mo | dépendances d'easyocr |

Le socle d'enregistrement pèse **~250 Mo**. Les **~700 Mo** restants ne
servent qu'à deux fonctions optionnelles.

Fait notable : la roue PyTorch officielle pèse **122 Mo** téléchargée,
contre 366 Mo dépliée dans le build. Le téléchargement à la demande est
donc bien plus léger que ce que la taille installée laisse croire.

## Ce qui existe déjà

Le contrat de plugin **est déjà écrit** dans le code, et c'est la
découverte qui rend ce projet peu risqué.

`src/filters/base.py` définit `FrameFilter` : une classe abstraite, une
méthode `process(frame)`, un `name`. `FilterChain` porte le garde-fou
décisif — un filtre trop lent ou qui lève une exception est **désactivé
à chaud**, et l'enregistrement continue.

`src/postprocess/base.py` définit `PostProcessor` avec la même règle,
écrite noir sur blanc dans son en-tête : « le runner n'échoue jamais.
Un processeur qui lève une exception produit un
`PostProcessResult(success=False)` et on passe au suivant — le fichier
original n'est jamais perdu ni modifié. »

**Conséquence : un plugin défaillant ne peut pas coûter un
enregistrement.** C'est la garantie la plus importante du système, et
elle est déjà en place. Il ne manque que le chargeur.

## Architecture

### Emplacement

```
%LOCALAPPDATA%\LuminaRecorder\
    extensions\        modules officiels installés depuis l'app
    plugins\           fichiers déposés par l'utilisateur
```

Hors du dossier programme, donc **sans droits administrateur**, et une
désinstallation de Lumina ne les efface pas. Au démarrage, ces dossiers
sont ajoutés au `sys.path` s'ils existent — mécanisme vérifié comme
fonctionnel sur une application gelée par PyInstaller.

### Anatomie d'un plugin

```python
from filters.base import FrameFilter

LUMINA_PLUGIN = {
    'nom': 'Filigrane',
    'description': 'Ajoute votre logo dans un coin',
    'auteur': 'yohandry',
    'version': '1.0',
    'api': 1,
}

class Plugin(FrameFilter):
    name = "Filigrane"

    def process(self, frame):
        ...
        return frame
```

Un fichier, un dictionnaire de métadonnées, une classe.

Le champ **`api`** est structurant : il permet de faire évoluer Lumina
sans casser les plugins existants, et de refuser proprement un plugin
écrit pour une version incompatible. C'est ce qui manque à la plupart
des systèmes de plugins improvisés, et ce qui les condamne au premier
changement d'interface.

### Le chargeur

1. Scanner les dossiers, lire `LUMINA_PLUGIN` **sans exécuter le reste
   du code** (analyse de l'arbre syntaxique) ;
2. Ne charger via `importlib` que les plugins **activés** par
   l'utilisateur ;
3. Un plugin qui échoue au chargement est marqué en erreur dans
   l'interface et ignoré — l'application démarre normalement.

### Points d'extension ouverts

Deux, volontairement — ceux dont le contrat existe et dont l'échec est
déjà sans conséquence :

- **Filtres temps réel** (`FrameFilter`) : filigrane, flou de visages,
  effet néon, vintage ;
- **Post-traitements** (`PostProcessor`) : conversion GIF, export,
  transcription alternative.

Les panneaux d'interface et les événements du cycle de vie sont
délibérément remis à plus tard : ils demandent d'exposer une API
d'interface stable, engagement qu'il est prématuré de prendre.

## Sécurité

Un plugin est du code Python qui s'exécute avec **tous les droits de
Lumina** : accès aux fichiers, au réseau, et aux images de l'écran
capturé.

Décision : **aucun dépôt en ligne**. L'utilisateur dépose lui-même les
fichiers ; aucune installation ne peut donc avoir lieu à son insu. Au
premier chargement d'un plugin tiers, un avertissement explicite :

> « Ce plugin s'exécute avec les droits de Lumina et voit l'image de
> votre écran. N'activez que des plugins dont vous connaissez
> l'origine. »

Les extensions officielles, elles, sont téléchargées depuis les
releases GitHub du projet et vérifiées par leur taille annoncée — le
mécanisme déjà utilisé et éprouvé par la mise à jour automatique.

## Interface

Un panneau « Extensions » présente deux listes :

- **Modules officiels** : nom, poids, bouton d'installation avec barre
  de progression (réutilise le composant de mise à jour existant) ;
- **Plugins détectés** : nom, auteur, version, interrupteur, et le
  message d'erreur si le chargement a échoué.

Les cases des fonctions non installées restent **visibles** dans les
panneaux existants, avec la mention « Nécessite un module de 200 Mo » :
l'utilisateur voit ce que l'application sait faire, et choisit ce qu'il
installe. Rien ne disparaît de l'interface.

## Machines peu puissantes

Le stockage n'est qu'une moitié du problème. `SystemAnalyzer` détecte
déjà le profil matériel ; il sera étendu pour :

- proposer d'emblée une résolution adaptée sur une machine faible ;
- prévenir avant d'activer un filtre coûteux ;
- s'appuyer sur le garde-fou existant de `FilterChain`, qui désactive
  déjà ce qui ne tient pas le budget d'image.

## Résultat attendu

| | Avant | Après |
|---|---|---|
| Setup téléchargé | 1050 Mo | **~250 Mo** |
| Installée, sans extension | 1050 Mo | ~250 Mo |
| Installée, tout activé | 1050 Mo | ~900 Mo |

Étape par étape : la purge seule fait passer le setup de 1050 à
~975 Mo (76 Mo de pyarrow). Le gain décisif vient de l'étape 3, quand
torch, ctranslate2, scipy, onnxruntime, pandas et av quittent le socle
avec les extensions qui les justifient.

## Limites assumées

**Les extensions exigent une connexion au premier usage.** Sur un poste
définitivement hors ligne, les sous-titres locaux resteront
inaccessibles. Un installeur complet sera proposé en second
téléchargement pour ces cas.

**Le contrat devient un engagement.** Dès qu'un plugin tiers existe,
`FrameFilter.process` et `PostProcessor.run` ne peuvent plus être
renommés librement. C'est le prix d'une plateforme — le champ `api`
existe pour gérer les évolutions inévitables.

**Aucune isolation des plugins.** Un plugin malveillant peut nuire.
L'absence de dépôt en ligne est la protection : elle exige un geste
délibéré de l'utilisateur pour installer du code tiers.

## Ordre de construction

Chaque étape est livrable indépendamment.

1. **Purge** — retirer pyarrow du build : **76 Mo**, aucun risque,
   aucune fonctionnalité perdue (aucun paquet ne le déclare, aucun
   code ne l'importe).
   `av` (63 Mo) part avec l'extension sous-titres à l'étape 3, car
   faster-whisper le déclare en dépendance : l'exclure du socle est
   sans risque une fois Whisper lui-même sorti du socle.
2. **Chargeur de plugins** + panneau Extensions.
3. **Extensions officielles téléchargeables** — le setup tombe à
   ~250 Mo.
4. **Trois plugins d'exemple** (filigrane, GIF, flou de visages) qui
   servent de documentation vivante du contrat.
5. **Garde-fous performances** pour les machines anciennes.
