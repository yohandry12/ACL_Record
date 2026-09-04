# Publier une version de Lumina

Procédure complète, de la machine de build à la release GitHub. Elle
couvre deux artefacts distincts : le **setup** de l'application et les
**archives d'extensions**, qui ne suivent pas le même rythme.

## Ce qui se publie, et quand

| Artefact | Tag | Quand le republier |
|---|---|---|
| `Lumina_Setup_x.y.z.exe` | `vx.y.z` | À chaque version |
| `lumina-ext-*.zip` | `ext-1.0` | Seulement si le contenu change |

Les extensions ont leur propre tag parce qu'elles changent rarement :
une nouvelle version de Lumina n'oblige pas à retélécharger 69 Mo de
Whisper. Le catalogue de `src/services/extension_installer.py` pointe
sur ce tag ; tant qu'il ne bouge pas, les installations existantes
continuent de fonctionner.

## 1. Les archives d'extensions

À faire **une fois**, ou quand une dépendance IA change de version.

```bash
python build_extensions.py            # les deux
python build_extensions.py sous_titres  # une seule
```

Le script installe les paquets avec pip, retire ceux que l'exécutable
embarque déjà, **exerce le module** dans un interpréteur séparé, puis
compresse.

**Ne pas alléger à l'aveugle.** Une première version du script
supprimait les `*.pyi` en les croyant réservés au développement.
`scikit-image` les lit à l'exécution via `lazy_loader`, qui résout ses
imports différés depuis `skimage/__init__.pyi` : l'archive OCR de
604 Mo échouait à l'import. Le contrôle `verifier()` l'a rattrapée
avant publication — c'est précisément sa raison d'être.

Ce contrôle va au-delà d'un simple `import` : les paquets à chargement
différé réussissent l'import puis échouent au premier usage réel. Le
champ `usage_test` de chaque recette exerce la chaîne qui compte.

**Pourquoi retirer des paquets.** `enregistrer_chemins_externes()` place
le dossier des extensions en **tête** de `sys.path`. Un numpy présent
dans l'archive masquerait donc celui du socle — au mieux du poids
inutile, au pire une incompatibilité d'ABI au premier appel. La liste
`DEJA_EMBARQUES` du script tient ce compte.

**Reporter les tailles.** Le script affiche en fin d'exécution les
valeurs à recopier dans `EXTENSIONS` :

```
sous_titres  'taille_octets': 72231409,   # 69 Mo compressés, 194 Mo dépliés
```

Ce n'est pas cosmétique : `download_setup` **détruit** un fichier dont
la taille reçue ne correspond pas à celle annoncée. Une valeur fausse
rend l'extension impossible à installer, après un téléchargement
complet. Un test vérifie la cohérence (`test_le_catalogue_annonce_des_tailles_coherentes`).

Publier ensuite les `.zip` de `dist_extensions/` sur une release GitHub
taguée `ext-1.0`.

## 2. Le setup de l'application

```bash
# Version dans src/version.py, puis :
rm -rf dist build LuminaRecorder.spec
build_installer.bat
```

Produit `dist/LuminaRecorder/` (~292 Mo) et
`dist_installer/Lumina_Setup_x.y.z.exe` (~119 Mo).

### Vérifications avant publication

```bash
# 1. Le socle est bien allégé
du -sm dist/LuminaRecorder                    # ~292 Mo

# 2. L'IA n'est PAS embarquée
dist/LuminaRecorder/LuminaRecorder.exe --diag-ai
# attendu : {"whisper": false, "ocr": false}

# 3. L'application démarre quand même
dist/LuminaRecorder/LuminaRecorder.exe        # la fenêtre doit s'ouvrir

# 4. La suite de tests
python -m pytest -q --ignore=tests/test_global_hotkey.py
```

Le point 2 est le plus important : un `true` signifie que PyInstaller a
réaspiré les paquets malgré les `--exclude-module`, et le setup pèsera
1 Go. C'est arrivé ; les exclusions doivent rester en place car les
imports gardés de `ocr_service.py` et `subtitles_processor.py` suffisent
à les faire revenir.

### Vérification de la chaîne complète

Une fois seulement, pour valider que les archives fonctionnent avec
l'exécutable réel — et non avec le Python de développement :

```bash
# Déplier une archive dans le dossier des extensions
%LOCALAPPDATA%\LuminaRecorder\extensions\

dist/LuminaRecorder/LuminaRecorder.exe --diag-ai
# attendu : {"whisper": true, "ocr": false}
```

Le passage de `false` à `true` prouve que le module est vu par
l'exécutable sans réinstallation.

## 3. La release GitHub

Pousser la branche d'abord (le tag est posé sur sa tête distante), puis :

```bash
python publish_release.py ext-1.0 "Extensions officielles 1.0" notes_ext.md \
    dist_extensions/lumina-ext-soustitres-1.0.zip dist_extensions/lumina-ext-ocr-1.0.zip

python publish_release.py v1.4.0 "Lumina Recorder 1.4.0" notes_1.4.0.md \
    dist_installer/Lumina_Setup_1.4.0.exe
```

Le script prend le token dans le gestionnaire d'identifiants git
(`git credential fill`) et ne l'affiche jamais. Il est idempotent : une
release existante est réutilisée, une pièce jointe de même nom est
remplacée. Il relit la release à la fin et affiche les tailles reçues —
à comparer à celles du catalogue pour les extensions.

Les installations existantes détectent la nouvelle version seules
(`services/update_checker.py` interroge l'API des releases et prend la
pièce jointe dont le nom contient « setup » et finit par `.exe`).

Le corps de la release sert de notes de version : il est affiché tel
quel dans la fenêtre de mise à jour.

## Migration depuis une version où l'IA était embarquée

Un utilisateur en 1.3.0 a Whisper et l'OCR dans son programme. En 1.4.0
ils n'y sont plus. Ses cases se grisent — d'où `get_extensions()` et
`install_extension()` dans le pont, qui laissent le panneau proposer
l'installation plutôt que de le laisser sans recours.

Les réglages, clés API et plugins ne sont pas touchés : ils vivent dans
`%LOCALAPPDATA%\LuminaRecorder\`, que le désinstallateur préserve.
