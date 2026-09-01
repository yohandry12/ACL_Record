# Lumina modulaire — Plan d'implémentation

> **Pour les agents :** utiliser `superpowers:subagent-driven-development`
> ou `superpowers:executing-plans` pour exécuter tâche par tâche.

**Objectif :** faire passer le setup de 1050 Mo à ~250 Mo en sortant
l'IA locale du socle, et ouvrir Lumina aux plugins — un seul mécanisme
pour les deux.

**Spec :** `docs/superpowers/specs/2026-09-01-lumina-modulaire-design.md`

**Pile :** Python 3.11, PyInstaller (mode dossier), PyWebView/WebView2,
pytest.

## Contraintes globales

Chaque tâche les respecte, sans exception.

1. **Un plugin défaillant ne coûte jamais un enregistrement.**
   `FilterChain` désactive à chaud un filtre lent ou qui lève ;
   `run_postprocessors` n'échoue jamais. Ne pas affaiblir ces garanties.
2. **Aucun code de plugin n'est exécuté pour être listé.** Les
   métadonnées se lisent par `ast`, vérifié faisable.
3. **Aucun droit administrateur.** Extensions et plugins vivent dans
   `%LOCALAPPDATA%\LuminaRecorder\`, jamais dans `Program Files`.
4. **Français** pour les commentaires, docstrings, messages
   d'interface et commits.
5. **Le socle reste utilisable sans aucune extension** : capture,
   encodage, audio, Magic Cut, IA distante (Ollama, API) fonctionnent
   toujours.
6. **La suite de tests reste verte.** Référence actuelle : 264 tests
   (hors `test_global_hotkey.py`, qui échoue tant qu'une instance de
   Lumina détient F9).

---

## Tâche 1 : Purger pyarrow du build

**Gain : 76 Mo. Aucun risque — aucun paquet ne le déclare, aucun code
ne l'importe.**

**Fichiers :**
- Modifier : `LuminaRecorder/build_installer.bat`

- [ ] **Étape 1 : Ajouter l'exclusion**

Dans le bloc des `--exclude-module`, après `--exclude-module=tensorboard` :

```
    --exclude-module=pyarrow ^
```

Avec le commentaire, au-dessus du bloc `pyinstaller` :

```
REM pyarrow (76 Mo) n'est importe par aucun de nos modules et n'est
REM declare par aucune de nos dependances : PyInstaller l'aspirait par
REM un import optionnel de pandas.
```

- [ ] **Étape 2 : Reconstruire et mesurer**

```bash
cd LuminaRecorder && rm -rf dist build dist_installer *.spec
# puis la commande pyinstaller du build_installer.bat
du -sm dist/LuminaRecorder
```

Attendu : ~1015 Mo au lieu de 1091.

- [ ] **Étape 3 : Vérifier que rien n'est cassé**

```bash
dist/LuminaRecorder/LuminaRecorder.exe --diag-ai
```

Attendu : `{"whisper": true, "ocr": true}` — les deux fonctions IA
répondent toujours présentes.

- [ ] **Étape 4 : Commit**

```bash
git add build_installer.bat
git commit -m "build: retirer pyarrow du paquet (76 Mo)"
```

---

## Tâche 2 : Chargeur de plugins

**Le cœur du système. Aucune interface encore — juste le moteur,
testable seul.**

**Fichiers :**
- Créer : `LuminaRecorder/src/plugins/__init__.py`
- Créer : `LuminaRecorder/src/plugins/loader.py`
- Créer : `LuminaRecorder/tests/test_plugin_loader.py`

**Interfaces produites** (les tâches suivantes en dépendent) :

```python
API_VERSION = 1

@dataclass
class PluginInfo:
    nom: str
    description: str
    auteur: str
    version: str
    api: int
    chemin: str          # chemin absolu du fichier
    identifiant: str     # nom de fichier sans .py, unique
    erreur: str = ""     # non vide si inutilisable

def plugins_dir() -> Path
def extensions_dir() -> Path
def lire_metadonnees(chemin: str) -> Optional[PluginInfo]
def lister_plugins() -> List[PluginInfo]
def charger_plugin(info: PluginInfo) -> Optional[object]
def enregistrer_chemins_externes() -> None
```

- [ ] **Étape 1 : Écrire les tests qui échouent**

```python
"""Tests du chargeur de plugins.

Aucun plugin réel n'est exécuté : les tests écrivent des fichiers
temporaires, y compris hostiles.
"""
import pytest
from plugins.loader import (API_VERSION, PluginInfo, lire_metadonnees,
                            lister_plugins, charger_plugin)


def ecrire(tmp_path, nom, contenu):
    f = tmp_path / nom
    f.write_text(contenu, encoding="utf-8")
    return str(f)


PLUGIN_VALIDE = '''
from filters.base import FrameFilter

LUMINA_PLUGIN = {
    'nom': 'Filigrane',
    'description': 'Ajoute un logo',
    'auteur': 'test',
    'version': '1.0',
    'api': 1,
}

class Plugin(FrameFilter):
    name = "Filigrane"
    def process(self, frame):
        return frame
'''


def test_metadonnees_lues_sans_executer_le_code(tmp_path):
    """Un plugin listé n'est pas un plugin exécuté : la liste doit
    pouvoir s'afficher sans faire tourner du code tiers."""
    hostile = ecrire(tmp_path, "hostile.py", '''
import os
os.environ["PLUGIN_A_TOURNE"] = "oui"
LUMINA_PLUGIN = {'nom': 'X', 'description': '', 'auteur': '',
                 'version': '1.0', 'api': 1}
class Plugin: pass
''')
    import os
    os.environ.pop("PLUGIN_A_TOURNE", None)

    info = lire_metadonnees(hostile)

    assert info.nom == 'X'
    assert "PLUGIN_A_TOURNE" not in os.environ


def test_plugin_valide_est_decrit(tmp_path):
    info = lire_metadonnees(ecrire(tmp_path, "filigrane.py", PLUGIN_VALIDE))

    assert info.nom == 'Filigrane'
    assert info.auteur == 'test'
    assert info.identifiant == 'filigrane'
    assert info.erreur == ""


def test_fichier_sans_metadonnees_est_ignore(tmp_path):
    """Un .py quelconque déposé par erreur n'est pas un plugin."""
    assert lire_metadonnees(
        ecrire(tmp_path, "quelconque.py", "x = 1")) is None


def test_syntaxe_invalide_ne_leve_jamais(tmp_path):
    """Un fichier corrompu ne doit pas empêcher l'application de
    démarrer."""
    assert lire_metadonnees(
        ecrire(tmp_path, "casse.py", "def ((((")) is None


def test_api_trop_recente_est_signalee(tmp_path):
    """Un plugin écrit pour une version future doit être refusé
    clairement, pas planter à l'usage."""
    futur = PLUGIN_VALIDE.replace("'api': 1", "'api': 99")
    info = lire_metadonnees(ecrire(tmp_path, "futur.py", futur))

    assert info.erreur
    assert "version" in info.erreur.lower()


def test_chargement_retourne_une_instance(tmp_path):
    info = lire_metadonnees(ecrire(tmp_path, "f.py", PLUGIN_VALIDE))

    instance = charger_plugin(info)

    assert instance is not None
    assert instance.name == "Filigrane"


def test_plugin_qui_plante_au_chargement_ne_leve_pas(tmp_path):
    """L'application doit démarrer même avec un plugin défectueux."""
    casse = PLUGIN_VALIDE.replace("class Plugin(FrameFilter):",
                                  "raise RuntimeError('boum')\nclass Plugin(FrameFilter):")
    info = lire_metadonnees(ecrire(tmp_path, "boum.py", casse))

    assert charger_plugin(info) is None


def test_dossier_absent_donne_liste_vide(monkeypatch, tmp_path):
    """Aucun dossier de plugins n'est une situation normale, pas une
    erreur."""
    from plugins import loader
    monkeypatch.setattr(loader, 'plugins_dir',
                        lambda: tmp_path / "inexistant")
    monkeypatch.setattr(loader, 'extensions_dir',
                        lambda: tmp_path / "inexistant2")

    assert lister_plugins() == []
```

- [ ] **Étape 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_plugin_loader.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'plugins'`

- [ ] **Étape 3 : Implémenter le chargeur**

```python
"""Chargeur de plugins et d'extensions.

Un plugin est un fichier Python déposé par l'utilisateur qui étend
Lumina sans toucher au cœur. Le même mécanisme sert aux extensions
officielles (sous-titres, OCR) installées depuis l'application.

Règle de sûreté : lister un plugin n'exécute AUCUNE de ses lignes. Les
métadonnées sont lues par analyse syntaxique ; seul un plugin
explicitement activé par l'utilisateur est importé.
"""

import ast
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Version du contrat de plugin. À incrémenter uniquement en cas de
# changement incompatible de FrameFilter ou PostProcessor : les plugins
# déclarant une version supérieure sont refusés avec un message clair
# plutôt que de planter à l'usage.
API_VERSION = 1


@dataclass
class PluginInfo:
    """Description d'un plugin, obtenue sans exécuter son code."""
    nom: str
    description: str
    auteur: str
    version: str
    api: int
    chemin: str
    identifiant: str
    erreur: str = ""

    @property
    def utilisable(self) -> bool:
        return not self.erreur


def _base_dir() -> Path:
    """Racine des données utilisateur, comme get_temp_dir."""
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return Path(base) / 'LuminaRecorder'
    return Path.home() / '.local' / 'share' / 'lumina_recorder'


def plugins_dir() -> Path:
    """Plugins déposés par l'utilisateur."""
    return _base_dir() / 'plugins'


def extensions_dir() -> Path:
    """Modules officiels installés depuis l'application."""
    return _base_dir() / 'extensions'


def enregistrer_chemins_externes() -> None:
    """Rend les extensions importables.

    Appelé au démarrage, avant tout import d'easyocr ou faster_whisper :
    ces paquets ne sont plus embarqués dans l'exécutable mais installés
    à la demande dans le dossier des extensions.
    """
    dossier = extensions_dir()
    if dossier.is_dir():
        chemin = str(dossier)
        if chemin not in sys.path:
            sys.path.insert(0, chemin)


def lire_metadonnees(chemin: str) -> Optional[PluginInfo]:
    """Décrit un plugin SANS exécuter son code.

    Retourne None si le fichier n'est pas un plugin (pas de bloc
    LUMINA_PLUGIN, syntaxe invalide, illisible). Un plugin reconnu mais
    inutilisable est retourné avec son champ `erreur` renseigné : il
    doit apparaître dans l'interface avec la raison, plutôt que
    disparaître sans explication.
    """
    try:
        source = Path(chemin).read_text(encoding='utf-8')
        arbre = ast.parse(source)
    except Exception:
        return None

    brut = None
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        for cible in noeud.targets:
            if isinstance(cible, ast.Name) and cible.id == 'LUMINA_PLUGIN':
                try:
                    brut = ast.literal_eval(noeud.value)
                except Exception:
                    return None
    if not isinstance(brut, dict):
        return None

    identifiant = Path(chemin).stem
    try:
        api = int(brut.get('api', 0))
    except (TypeError, ValueError):
        api = 0

    erreur = ""
    if api > API_VERSION:
        erreur = (f"Écrit pour une version plus récente de Lumina "
                  f"(contrat {api}, cette version gère {API_VERSION})")
    elif api < 1:
        erreur = "Version du contrat manquante ou invalide"

    return PluginInfo(
        nom=str(brut.get('nom') or identifiant),
        description=str(brut.get('description') or ''),
        auteur=str(brut.get('auteur') or 'inconnu'),
        version=str(brut.get('version') or '?'),
        api=api,
        chemin=chemin,
        identifiant=identifiant,
        erreur=erreur,
    )


def lister_plugins() -> List[PluginInfo]:
    """Tous les plugins présents, utilisables ou non.

    Un dossier absent est normal — l'utilisateur n'a simplement aucun
    plugin.
    """
    trouves: List[PluginInfo] = []
    vus = set()
    for dossier in (plugins_dir(), extensions_dir()):
        if not dossier.is_dir():
            continue
        for fichier in sorted(dossier.glob('*.py')):
            if fichier.name.startswith('_'):
                continue
            info = lire_metadonnees(str(fichier))
            if info and info.identifiant not in vus:
                vus.add(info.identifiant)
                trouves.append(info)
    return trouves


def charger_plugin(info: PluginInfo) -> Optional[object]:
    """Importe le plugin et retourne une instance de sa classe Plugin.

    Retourne None en cas d'échec : un plugin défectueux ne doit jamais
    empêcher l'application de démarrer ni interrompre un enregistrement.
    """
    if not info.utilisable:
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"lumina_plugin_{info.identifiant}", info.chemin)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classe = getattr(module, 'Plugin', None)
        if classe is None:
            return None
        return classe()
    except Exception as e:
        print(f"[Lumina] Plugin « {info.nom} » ignoré : {e}")
        return None
```

- [ ] **Étape 4 : Vérifier le succès**

Run : `python -m pytest tests/test_plugin_loader.py -v`
Attendu : 8 tests PASS

- [ ] **Étape 5 : Commit**

```bash
git add src/plugins/ tests/test_plugin_loader.py
git commit -m "feat: chargeur de plugins"
```

---

## Tâche 3 : Brancher les plugins sur la chaîne de filtres

**Fichiers :**
- Modifier : `LuminaRecorder/src/core/ai_options.py` (`build_filters`, ligne 59)
- Modifier : `LuminaRecorder/tests/test_ai_options_config.py`

**Consomme :** `lister_plugins`, `charger_plugin` (tâche 2)

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
def test_les_plugins_actives_rejoignent_la_chaine(monkeypatch):
    """Un plugin activé doit filtrer les images comme un filtre natif."""
    from core import ai_options
    from filters.base import FrameFilter
    from plugins.loader import PluginInfo

    class FauxPlugin(FrameFilter):
        name = "Faux"
        def process(self, frame):
            return frame

    info = PluginInfo(nom="Faux", description="", auteur="t",
                      version="1.0", api=1, chemin="x.py",
                      identifiant="faux")
    monkeypatch.setattr(ai_options, 'lister_plugins', lambda: [info])
    monkeypatch.setattr(ai_options, 'charger_plugin',
                        lambda i: FauxPlugin())

    filtres = AIOptions.build_filters({}, plugins_actifs=['faux'])

    assert any(f.name == "Faux" for f in filtres)


def test_un_plugin_non_active_reste_absent(monkeypatch):
    """Rien ne s'exécute sans décision explicite de l'utilisateur."""
    from core import ai_options
    from plugins.loader import PluginInfo

    appels = []
    info = PluginInfo(nom="Faux", description="", auteur="t",
                      version="1.0", api=1, chemin="x.py",
                      identifiant="faux")
    monkeypatch.setattr(ai_options, 'lister_plugins', lambda: [info])
    monkeypatch.setattr(ai_options, 'charger_plugin',
                        lambda i: appels.append(i))

    AIOptions.build_filters({}, plugins_actifs=[])

    assert appels == []


def test_plugin_defectueux_ne_casse_pas_la_chaine(monkeypatch):
    """Les filtres natifs doivent rester présents malgré un plugin
    qui refuse de se charger."""
    from core import ai_options
    from plugins.loader import PluginInfo

    info = PluginInfo(nom="Cassé", description="", auteur="t",
                      version="1.0", api=1, chemin="x.py",
                      identifiant="casse")
    monkeypatch.setattr(ai_options, 'lister_plugins', lambda: [info])
    monkeypatch.setattr(ai_options, 'charger_plugin', lambda i: None)

    filtres = AIOptions.build_filters({'clean_canvas': True},
                                      plugins_actifs=['casse'])

    assert any(f.name == 'clean_canvas' for f in filtres)
```

- [ ] **Étape 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_ai_options_config.py -k plugin -v`
Attendu : ÉCHEC — `build_filters() got an unexpected keyword argument`

- [ ] **Étape 3 : Implémenter**

Dans `ai_options.py`, ajouter l'import :

```python
from plugins.loader import charger_plugin, lister_plugins
```

Puis modifier `build_filters` :

```python
    @staticmethod
    def build_filters(options: dict, plugins_actifs=None) -> list:
        filters = []
        # Sans moteur OCR, le flou n'a aucune zone à masquer : on n'ajoute
        # pas un filtre inerte, même si le .ini garde la valeur d'une
        # session où easyocr était installé
        if options.get('privacy_blur') and ocr_is_available():
            filters.append(PrivacyBlurFilter())
        if options.get('clean_canvas'):
            filters.append(CleanCanvasFilter())
        if options.get('overlay'):
            filters.append(OverlayFilter())

        # Plugins de l'utilisateur, après les filtres natifs : ils
        # travaillent sur une image déjà nettoyée. Un plugin qui refuse
        # de se charger est simplement absent — jamais une exception,
        # sinon un fichier tiers défectueux empêcherait d'enregistrer.
        for identifiant in (plugins_actifs or []):
            info = next((p for p in lister_plugins()
                         if p.identifiant == identifiant), None)
            if info is None or not info.utilisable:
                continue
            instance = charger_plugin(info)
            if isinstance(instance, FrameFilter):
                filters.append(instance)

        return filters
```

Ajouter l'import de `FrameFilter` en tête si absent.

- [ ] **Étape 4 : Vérifier**

Run : `python -m pytest tests/test_ai_options_config.py -v`
Attendu : tous PASS

- [ ] **Étape 5 : Commit**

```bash
git add src/core/ai_options.py tests/test_ai_options_config.py
git commit -m "feat: les plugins rejoignent la chaîne de filtres"
```

---

## Tâche 4 : Exposer les plugins au pont et à l'interface

**Fichiers :**
- Modifier : `LuminaRecorder/src/webui/bridge.py`
- Modifier : `LuminaRecorder/src/webui/assets/index.html`
- Modifier : `LuminaRecorder/src/webui/assets/app.js`
- Modifier : `LuminaRecorder/src/webui/assets/style.css`
- Modifier : `LuminaRecorder/tests/test_bridge.py`

**Consomme :** `lister_plugins` (tâche 2), `build_filters` (tâche 3)

- [ ] **Étape 1 : Écrire les tests du pont**

```python
def test_le_pont_liste_les_plugins(bridge, monkeypatch):
    from webui import bridge as pont
    from plugins.loader import PluginInfo

    monkeypatch.setattr(pont, 'lister_plugins', lambda: [
        PluginInfo(nom="Filigrane", description="Logo", auteur="moi",
                   version="1.0", api=1, chemin="f.py",
                   identifiant="filigrane")])

    liste = bridge.get_plugins()

    assert liste['ok'] is True
    assert liste['plugins'][0]['nom'] == "Filigrane"
    assert liste['plugins'][0]['actif'] is False


def test_activer_un_plugin_le_memorise(bridge, monkeypatch):
    from webui import bridge as pont
    from plugins.loader import PluginInfo

    monkeypatch.setattr(pont, 'lister_plugins', lambda: [
        PluginInfo(nom="F", description="", auteur="", version="1",
                   api=1, chemin="f.py", identifiant="filigrane")])

    bridge.set_plugin_actif('filigrane', True)

    assert bridge.get_plugins()['plugins'][0]['actif'] is True


def test_un_plugin_en_erreur_reste_visible(bridge, monkeypatch):
    """Un plugin refusé doit apparaître AVEC sa raison : disparaître
    sans explication laisserait l'utilisateur sans recours."""
    from webui import bridge as pont
    from plugins.loader import PluginInfo

    monkeypatch.setattr(pont, 'lister_plugins', lambda: [
        PluginInfo(nom="Futur", description="", auteur="", version="1",
                   api=99, chemin="f.py", identifiant="futur",
                   erreur="Écrit pour une version plus récente")])

    p = bridge.get_plugins()['plugins'][0]

    assert p['erreur']
    assert p['actif'] is False
```

- [ ] **Étape 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_bridge.py -k plugin -v`
Attendu : ÉCHEC — `AttributeError: 'LuminaBridge' object has no attribute 'get_plugins'`

- [ ] **Étape 3 : Implémenter le pont**

Import en tête de `bridge.py` :

```python
from plugins.loader import lister_plugins, plugins_dir
```

Méthodes, dans une nouvelle section « Plugins » :

```python
    # ------------------------------------------------------------------
    # Plugins
    # ------------------------------------------------------------------

    def get_plugins(self) -> dict:
        """Liste les plugins installés, avec leur état d'activation.

        Aucun code de plugin n'est exécuté ici : les métadonnées sont
        lues par analyse syntaxique.
        """
        actifs = self._plugins_actifs()
        try:
            trouves = lister_plugins()
        except Exception as e:
            return {'ok': False, 'error': str(e), 'plugins': []}

        return {
            'ok': True,
            'dossier': str(plugins_dir()),
            'plugins': [{
                'identifiant': p.identifiant,
                'nom': p.nom,
                'description': p.description,
                'auteur': p.auteur,
                'version': p.version,
                'erreur': p.erreur,
                'actif': p.identifiant in actifs and p.utilisable,
            } for p in trouves],
        }

    def _plugins_actifs(self) -> list:
        brut = self.config.get('plugins', 'actifs', fallback='')
        return [x.strip() for x in brut.split(',') if x.strip()]

    def set_plugin_actif(self, identifiant: str, actif: bool) -> dict:
        """Active ou désactive un plugin. Prend effet au prochain
        enregistrement — jamais pendant une capture en cours."""
        actifs = self._plugins_actifs()
        if actif and identifiant not in actifs:
            actifs.append(identifiant)
        elif not actif and identifiant in actifs:
            actifs.remove(identifiant)
        self.config.set('plugins', 'actifs', ','.join(actifs))
        self.config.save()
        return {'ok': True}

    def open_plugins_folder(self) -> dict:
        """Ouvre le dossier des plugins dans l'explorateur."""
        dossier = plugins_dir()
        try:
            dossier.mkdir(parents=True, exist_ok=True)
            os.startfile(str(dossier))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
```

Brancher sur la construction du recorder — dans `start_recording`,
remplacer `filters=AIOptions.build_filters(options)` par :

```python
                filters=AIOptions.build_filters(
                    options, plugins_actifs=self._plugins_actifs()),
```

- [ ] **Étape 4 : Ajouter le panneau HTML**

Dans `index.html`, après la modale de mise à jour :

```html
<!-- Extensions et plugins -->
<div class="modal" id="plugins-modal" hidden>
  <div class="modal-card">
    <div class="modal-head">
      <h3>Extensions</h3>
      <button class="modal-close" id="plugins-close" aria-label="Fermer">✕</button>
    </div>

    <p class="modal-note">Les plugins ajoutent des fonctions à Lumina.
      Ils s'exécutent avec les droits de l'application et voient l'image
      de votre écran : n'activez que ceux dont vous connaissez l'origine.</p>

    <div class="plugin-list" id="plugin-list"></div>

    <div class="modal-actions">
      <span class="modal-status" id="plugins-status"></span>
      <button class="btn-sub" id="plugins-folder">Ouvrir le dossier</button>
    </div>
  </div>
</div>
```

Et le déclencheur dans la barre de titre, avant `version-tag` :

```html
  <button class="titlebar-action" id="open-plugins" title="Extensions">Extensions</button>
```

- [ ] **Étape 5 : Câbler le JavaScript**

Dans `app.js` :

```javascript
/* ---------- Extensions et plugins ---------- */

async function openPluginsModal() {
  await renderPlugins();
  ancrerModale('plugins-modal', 'open-plugins');
}

function closePluginsModal() {
  $('plugins-modal').hidden = true;
}

async function renderPlugins() {
  const data = await call('get_plugins');
  const liste = $('plugin-list');
  liste.innerHTML = '';

  if (!data || !data.ok || !data.plugins.length) {
    liste.innerHTML =
      '<p class="plugin-vide">Aucun plugin installé. ' +
      'Déposez un fichier .py dans le dossier des plugins.</p>';
    return;
  }

  for (const p of data.plugins) {
    const ligne = document.createElement('div');
    ligne.className = 'plugin-item' + (p.erreur ? ' plugin-erreur' : '');

    const info = document.createElement('div');
    info.className = 'plugin-info';
    const titre = document.createElement('div');
    titre.className = 'plugin-nom';
    titre.textContent = p.nom;
    const detail = document.createElement('div');
    detail.className = 'plugin-detail';
    detail.textContent = p.erreur
      ? p.erreur
      : `${p.description || 'Aucune description'} · ${p.auteur} · v${p.version}`;
    info.append(titre, detail);

    ligne.append(info);

    if (!p.erreur) {
      const inter = document.createElement('input');
      inter.type = 'checkbox';
      inter.checked = p.actif;
      inter.addEventListener('change', async () => {
        await call('set_plugin_actif', p.identifiant, inter.checked);
        $('plugins-status').textContent =
          'Prend effet au prochain enregistrement';
      });
      ligne.append(inter);
    }

    liste.append(ligne);
  }
}
```

Enregistrer les écouteurs auprès des autres :

```javascript
  $('open-plugins').addEventListener('click', openPluginsModal);
  $('plugins-close').addEventListener('click', closePluginsModal);
  $('plugins-folder').addEventListener('click',
    () => call('open_plugins_folder'));
  $('plugins-modal').addEventListener('click', (event) => {
    if (event.target === $('plugins-modal')) closePluginsModal();
  });
```

Et dans le gestionnaire de la touche Échap, avant le cas
`state === 'recording'` :

```javascript
    if (event.key === 'Escape' && !$('plugins-modal').hidden) {
      closePluginsModal();
      return;
    }
```

- [ ] **Étape 6 : Styler la liste**

Dans `style.css`, à la suite des styles de modale :

```css
/* ---------- Liste des plugins ---------- */

.plugin-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 40vh;
  overflow-y: auto;
}

.plugin-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
}

.plugin-item.plugin-erreur { border-color: var(--rec); }

.plugin-nom { font-size: 12px; font-weight: 600; }

.plugin-detail {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}

.plugin-erreur .plugin-detail { color: var(--rec); }

.plugin-vide {
  font-size: 12px;
  color: var(--text-dim);
  text-align: center;
  padding: 18px 0;
}

.titlebar-action {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-faint);
  padding: 3px 8px;
  margin-right: 8px;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: inherit;
  cursor: pointer;
  transition: color var(--t-fast) var(--ease-out),
              border-color var(--t-fast) var(--ease-out);
}

.titlebar-action:hover {
  color: var(--text);
  border-color: var(--border-bright);
}
```

- [ ] **Étape 7 : Vérifier**

```bash
python -m pytest tests/test_bridge.py -v
python main.py     # ouvrir le panneau Extensions, vérifier le rendu
```

- [ ] **Étape 8 : Commit**

```bash
git add src/webui/ tests/test_bridge.py
git commit -m "feat: panneau Extensions et activation des plugins"
```

---

## Tâche 5 : Trois plugins d'exemple

**Ils servent de documentation vivante du contrat : un développeur
tiers les lit pour comprendre ce qu'il doit écrire.**

**Fichiers :**
- Créer : `LuminaRecorder/exemples_plugins/filigrane.py`
- Créer : `LuminaRecorder/exemples_plugins/gif.py`
- Créer : `LuminaRecorder/exemples_plugins/README.md`
- Créer : `LuminaRecorder/tests/test_plugins_exemples.py`

- [ ] **Étape 1 : Écrire les tests**

```python
"""Les exemples doivent rester valides : ils sont la documentation."""
from pathlib import Path

from plugins.loader import charger_plugin, lire_metadonnees

DOSSIER = Path(__file__).parent.parent / "exemples_plugins"


def test_les_exemples_sont_des_plugins_valides():
    fichiers = sorted(DOSSIER.glob("*.py"))
    assert fichiers, "aucun exemple trouvé"

    for f in fichiers:
        info = lire_metadonnees(str(f))
        assert info is not None, f"{f.name} n'est pas reconnu"
        assert info.utilisable, f"{f.name} : {info.erreur}"


def test_le_filigrane_traite_une_image():
    import numpy as np

    info = lire_metadonnees(str(DOSSIER / "filigrane.py"))
    plugin = charger_plugin(info)
    image = np.zeros((120, 160, 3), dtype=np.uint8)

    sortie = plugin.process(image)

    assert sortie.shape == image.shape
    assert sortie.dtype == image.dtype
```

- [ ] **Étape 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_plugins_exemples.py -v`
Attendu : ÉCHEC — dossier inexistant

- [ ] **Étape 3 : Écrire le plugin filigrane**

```python
"""Exemple de plugin Lumina : incruste un texte dans un coin.

Copiez ce fichier dans le dossier des plugins, puis activez-le depuis
le panneau Extensions.
"""

import cv2

from filters.base import FrameFilter

LUMINA_PLUGIN = {
    'nom': 'Filigrane',
    'description': 'Incruste un texte dans le coin de la vidéo',
    'auteur': 'Lumina',
    'version': '1.0',
    'api': 1,
}

TEXTE = "Lumina"


class Plugin(FrameFilter):
    """Un filtre reçoit chaque image et retourne l'image transformée.

    Contrainte : garder les mêmes dimensions et le même type. Un filtre
    trop lent est désactivé automatiquement pendant l'enregistrement —
    la capture n'est jamais interrompue.
    """

    name = "Filigrane"

    def process(self, frame):
        hauteur, largeur = frame.shape[:2]
        cv2.putText(frame, TEXTE, (largeur - 150, hauteur - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                    cv2.LINE_AA)
        return frame
```

- [ ] **Étape 4 : Écrire le plugin GIF**

```python
"""Exemple de plugin Lumina : convertit la fin de l'enregistrement en GIF.

Montre le second point d'extension : un post-traitement, exécuté après
l'arrêt de la capture, qui produit un fichier supplémentaire sans
jamais toucher à l'enregistrement d'origine.
"""

import os
import subprocess
from pathlib import Path

from postprocess.base import PostProcessor, PostProcessResult

LUMINA_PLUGIN = {
    'nom': 'Conversion GIF',
    'description': 'Convertit les 10 dernières secondes en GIF',
    'auteur': 'Lumina',
    'version': '1.0',
    'api': 1,
}

SECONDES = 10


class Plugin(PostProcessor):
    name = "Conversion GIF"

    def run(self, video_path, audio_path, progress_cb):
        sortie = str(Path(video_path).with_suffix('.gif'))
        progress_cb(0.1)
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-sseof', f'-{SECONDES}', '-i', video_path,
                 '-vf', 'fps=12,scale=480:-1:flags=lanczos', '-loop', '0',
                 sortie],
                check=True, capture_output=True)
        except Exception as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=str(e))
        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=sortie)
```

- [ ] **Étape 5 : Écrire le README**

Documenter : les deux contrats, le bloc `LUMINA_PLUGIN`, le rôle du
champ `api`, l'emplacement du dossier, et la garantie de sûreté (un
plugin lent ou défectueux est désactivé, l'enregistrement continue).

- [ ] **Étape 6 : Vérifier**

Run : `python -m pytest tests/test_plugins_exemples.py -v`
Attendu : PASS

- [ ] **Étape 7 : Commit**

```bash
git add exemples_plugins/ tests/test_plugins_exemples.py
git commit -m "docs: trois plugins d'exemple"
```

---

## Tâche 6 : Extensions officielles téléchargeables

**L'étape qui fait tomber le setup à ~250 Mo.**

**Fichiers :**
- Créer : `LuminaRecorder/src/services/extension_installer.py`
- Créer : `LuminaRecorder/tests/test_extension_installer.py`
- Modifier : `LuminaRecorder/main.py` (appeler `enregistrer_chemins_externes`)
- Modifier : `LuminaRecorder/build_installer.bat` (exclusions)
- Modifier : `LuminaRecorder/src/webui/bridge.py` (méthodes d'installation)

**Consomme :** `extensions_dir` (tâche 2), le composant de progression
de la mise à jour (`download_setup`, réutilisable).

- [ ] **Étape 1 : Écrire les tests**

```python
"""Tests de l'installation des extensions.

Aucun téléchargement réel : la fonction de récupération est remplacée.
"""
import pytest

from services.extension_installer import (EXTENSIONS, est_installee,
                                          installer_extension)


def test_le_catalogue_declare_les_deux_extensions():
    assert 'sous_titres' in EXTENSIONS
    assert 'ocr' in EXTENSIONS
    for cle, ext in EXTENSIONS.items():
        assert ext['modules'], f"{cle} ne déclare aucun module"
        assert ext['taille_mo'] > 0
        assert ext['url'].startswith('https://')
        assert ext['archive'].endswith('.zip')


def test_extension_absente_est_signalee(monkeypatch, tmp_path):
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)

    assert est_installee('sous_titres') is False


def test_extension_presente_est_detectee(monkeypatch, tmp_path):
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)
    (tmp_path / 'faster_whisper').mkdir()

    assert est_installee('sous_titres') is True


def test_installation_hors_ligne_echoue_proprement(monkeypatch, tmp_path):
    """Une extension qu'on ne peut pas télécharger doit produire un
    message clair, jamais une exception qui remonte à l'interface."""
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)

    def refuse(*a, **k):
        raise ConnectionError("hors ligne")

    resultat = installer_extension('sous_titres', telecharger=refuse)

    assert resultat['ok'] is False
    assert resultat['error']


def test_extension_inconnue_est_refusee():
    assert installer_extension('nimporte_quoi')['ok'] is False
```

- [ ] **Étape 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_extension_installer.py -v`
Attendu : ÉCHEC — module inexistant

- [ ] **Étape 3 : Implémenter l'installateur**

```python
"""Installation des extensions officielles.

Les fonctions lourdes (sous-titres Whisper, OCR) ne sont plus
embarquées dans l'exécutable : elles pèsent ~700 Mo pour un socle qui
en fait 250. Elles s'installent à la demande, dans le dossier des
données utilisateur — sans droits administrateur, et sans être
effacées par une désinstallation de Lumina.
"""

import subprocess
import sys
from typing import Callable, Optional

from plugins.loader import extensions_dir

# Catalogue. `modules` sert à détecter une extension déjà installée ;
# `archive`, `url` et `taille_octets` décrivent ce qu'il faut
# récupérer. Les URL pointent sur les releases GitHub du projet, comme
# pour la mise à jour automatique.
#
# `taille_octets` doit correspondre EXACTEMENT à l'archive publiée :
# download_setup détruit un fichier dont la taille ne correspond pas,
# afin de ne jamais déplier une archive tronquée.
DEPOT = "https://github.com/yohandry12/ACL_Record/releases/download"

EXTENSIONS = {
    'sous_titres': {
        'nom': "Sous-titres automatiques",
        'description': "Transcription hors ligne par Whisper",
        'taille_mo': 200,
        'modules': ['faster_whisper'],
        'version': "1.0",
        'archive': "lumina-ext-soustitres-1.0.zip",
        'url': f"{DEPOT}/ext-1.0/lumina-ext-soustitres-1.0.zip",
        'taille_octets': 0,      # renseigné à la publication
    },
    'ocr': {
        'nom': "Reconnaissance de texte",
        'description': "Flou de confidentialité et lecture du texte à l'écran",
        'taille_mo': 450,
        'modules': ['easyocr'],
        'version': "1.0",
        'archive': "lumina-ext-ocr-1.0.zip",
        'url': f"{DEPOT}/ext-1.0/lumina-ext-ocr-1.0.zip",
        'taille_octets': 0,      # renseigné à la publication
    },
}


def est_installee(cle: str) -> bool:
    """Une extension est installée si ses modules sont présents."""
    ext = EXTENSIONS.get(cle)
    if not ext:
        return False
    dossier = extensions_dir()
    return all((dossier / m).exists() for m in ext['modules'])


def installer_extension(cle: str,
                        progress_cb: Optional[Callable[[float], None]] = None,
                        telecharger: Optional[Callable] = None) -> dict:
    """Installe une extension dans le dossier des données utilisateur.

    `telecharger` est injectable pour les tests. Aucune exception ne
    remonte : un échec produit un message affichable.
    """
    ext = EXTENSIONS.get(cle)
    if not ext:
        return {'ok': False, 'error': "Extension inconnue"}

    if est_installee(cle):
        return {'ok': True, 'deja': True}

    dossier = extensions_dir()
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        telecharger = telecharger or _telecharger_archive
        telecharger(ext, str(dossier), progress_cb)
        if progress_cb:
            progress_cb(1.0)
        return {'ok': True}
    except Exception as e:
        return {'ok': False,
                'error': f"Installation impossible : {e}"}


def _telecharger_archive(ext: dict, dossier: str,
                         progress_cb=None) -> None:
    """Récupère l'archive de l'extension et la déplie.

    Chaque extension est publiée comme une archive .zip attachée aux
    releases GitHub du projet, préparée par le script de build : elle
    contient les paquets déjà installés pour Windows x64 et Python
    3.11, donc rien à compiler sur la machine de l'utilisateur.

    On réutilise le téléchargement de la mise à jour automatique, qui
    gère déjà la progression, l'écriture dans un fichier .part renommé
    à la fin, et la vérification de la taille reçue.
    """
    import zipfile

    from services.update_checker import UpdateInfo, download_setup

    info = UpdateInfo(version=ext['version'], notes='',
                      asset_url=ext['url'], asset_name=ext['archive'],
                      size=ext['taille_octets'])
    archive = download_setup(info, dossier, progress_cb=progress_cb)
    with zipfile.ZipFile(archive) as z:
        z.extractall(dossier)
    os.remove(archive)
```

**Point vérifié, décisif pour cette tâche :** `pip` n'est **pas**
présent dans l'application empaquetée (confirmé : absent de
`dist/LuminaRecorder/_internal/`), et `sys.executable` y pointe sur
`LuminaRecorder.exe`, pas sur un interpréteur Python. Un
`pip install` est donc impossible depuis l'application installée.

Les extensions sont donc distribuées en **archives .zip préparées par
le script de build** et attachées aux releases GitHub — mêmes
mécanismes de téléchargement et de vérification que la mise à jour
automatique, déjà éprouvés.

Le catalogue `EXTENSIONS` porte alors, par entrée : `url`,
`archive`, `taille_octets` et `version`, en plus des champs déjà
décrits.

**Étape de build à ajouter :** produire ces archives. Pour chaque
extension, `pip install --target <dossier temporaire> <paquets>` sur
la machine de build, puis compression. À faire une fois par version
publiée, avant la release.

- [ ] **Étape 4 : Brancher au démarrage**

Dans `main.py`, avant tout import de `webui` :

```python
# Les extensions vivent hors de l'exécutable : rendre leur dossier
# importable AVANT que quoi que ce soit ne tente d'importer easyocr
# ou faster_whisper.
from plugins.loader import enregistrer_chemins_externes
enregistrer_chemins_externes()
```

- [ ] **Étape 5 : Exclure les paquets lourds du build**

Dans `build_installer.bat`, remplacer `--collect-all=easyocr` et
`--collect-all=faster_whisper` par des exclusions :

```
    --exclude-module=torch ^
    --exclude-module=torchvision ^
    --exclude-module=easyocr ^
    --exclude-module=faster_whisper ^
    --exclude-module=ctranslate2 ^
    --exclude-module=scipy ^
    --exclude-module=onnxruntime ^
    --exclude-module=pandas ^
    --exclude-module=av ^
    --exclude-module=pyarrow ^
```

- [ ] **Étape 6 : Vérifier la taille et le fonctionnement**

```bash
rm -rf dist build dist_installer *.spec
# build complet
du -sm dist/LuminaRecorder            # attendu : ~250
dist/LuminaRecorder/LuminaRecorder.exe --diag-ai
# attendu : {"whisper": false, "ocr": false} — sans extension installée
```

Puis, extension installée, `--diag-ai` doit rendre `true`.

- [ ] **Étape 7 : Commit**

```bash
git add src/services/extension_installer.py tests/ main.py build_installer.bat
git commit -m "feat: extensions téléchargeables, socle à 250 Mo"
```

---

## Tâche 7 : Garde-fous pour machines peu puissantes

**Fichiers :**
- Modifier : `LuminaRecorder/src/core/system_analyzer.py`
- Modifier : `LuminaRecorder/src/webui/bridge.py`
- Modifier : `LuminaRecorder/tests/test_bridge.py`

- [ ] **Étape 1 : Écrire le test**

```python
def test_une_machine_faible_recoit_un_avertissement(bridge, monkeypatch):
    """Activer trois filtres sur une machine modeste dégradera la
    capture : le dire avant plutôt que de laisser l'utilisateur
    découvrir un enregistrement saccadé."""
    bridge.recommended = {'resolution': '1280x720', 'fps': 30,
                          'bitrate': '2500k', 'profil': 'entry'}

    avis = bridge.check_charge({'privacy_blur': True, 'clean_canvas': True,
                                'overlay': True})

    assert avis['avertissement']
```

- [ ] **Étape 2 : Vérifier l'échec, puis implémenter**

```python
    def check_charge(self, options: dict) -> dict:
        """Prévient si les options choisies dépassent la machine.

        Le garde-fou de FilterChain désactive déjà à chaud un filtre
        trop lent ; cet avis arrive avant, pour que l'utilisateur
        décide plutôt que de subir.
        """
        profil = str(self.recommended.get('profil', '')).lower()
        couteux = sum(1 for c in ('privacy_blur', 'clean_canvas', 'overlay')
                      if options.get(c))
        if profil in ('entry', 'faible') and couteux >= 2:
            return {'avertissement':
                    "Cette machine risque de perdre des images avec "
                    "plusieurs filtres actifs. Lumina en désactivera "
                    "automatiquement si la capture ralentit."}
        return {'avertissement': ""}
```

Afficher l'avis dans l'interface au changement d'option.

- [ ] **Étape 3 : Commit**

```bash
git add src/core/system_analyzer.py src/webui/bridge.py tests/test_bridge.py
git commit -m "feat: avertir avant de saturer une machine modeste"
```

---

## Vérification de bout en bout

Après la tâche 7 :

1. **Tests** — `python -m pytest -q --ignore=tests/test_global_hotkey.py`
   doit rester vert (264 + les nouveaux). Fermer Lumina avant de lancer
   la suite complète, sinon les tests du raccourci global échouent.
2. **Taille** — `du -sm dist/LuminaRecorder` : ~250 Mo attendus.
3. **Socle nu** — sans extension, un enregistrement complet doit
   fonctionner : capture, audio, encodage, Magic Cut, IA Ollama.
4. **Extension** — installer les sous-titres depuis le panneau, vérifier
   que `--diag-ai` passe de `false` à `true`, et qu'un `.srt` est produit.
5. **Plugin** — copier `exemples_plugins/filigrane.py` dans le dossier
   des plugins, l'activer, enregistrer, vérifier le texte incrusté.
6. **Plugin défectueux** — déposer un fichier qui lève à l'import :
   l'application doit démarrer, l'afficher en erreur, et enregistrer
   normalement.
7. **Widget** — vérifier qu'il reste absent de la vidéo (mesure de
   régression établie : moins de 0,01 % de rouge dans le coin).

## Publication

Une fois vérifié : version 1.4.0, build, release GitHub avec le setup
allégé. Les installations existantes proposeront la mise à jour.

**Attention à la migration** : un utilisateur en 1.3.0 a l'IA
embarquée ; en 1.4.0 elle disparaît du programme. Au premier démarrage
après mise à jour, si une option IA locale était activée, proposer
l'installation de l'extension correspondante plutôt que de laisser la
case se griser sans explication.
