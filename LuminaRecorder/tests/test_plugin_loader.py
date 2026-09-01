"""Tests du chargeur de plugins.

Aucun plugin réel n'est exécuté : les tests écrivent des fichiers
temporaires, y compris hostiles.
"""

import os

from plugins.loader import (API_VERSION, PluginInfo, charger_plugin,
                            lire_metadonnees, lister_plugins)


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
    assert info.utilisable is True


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
    assert info.utilisable is False


def test_api_manquante_est_refusee(tmp_path):
    """Sans version de contrat déclarée, on ne peut rien garantir."""
    sans = PLUGIN_VALIDE.replace("'api': 1,", "")
    info = lire_metadonnees(ecrire(tmp_path, "sans.py", sans))

    assert info.utilisable is False


def test_chargement_retourne_une_instance(tmp_path):
    info = lire_metadonnees(ecrire(tmp_path, "f.py", PLUGIN_VALIDE))

    instance = charger_plugin(info)

    assert instance is not None
    assert instance.name == "Filigrane"


def test_plugin_qui_plante_au_chargement_ne_leve_pas(tmp_path):
    """L'application doit démarrer même avec un plugin défectueux."""
    casse = PLUGIN_VALIDE.replace(
        "class Plugin(FrameFilter):",
        "raise RuntimeError('boum')\nclass Plugin(FrameFilter):")
    info = lire_metadonnees(ecrire(tmp_path, "boum.py", casse))

    assert charger_plugin(info) is None


def test_plugin_sans_classe_plugin_est_ignore(tmp_path):
    """Le contrat exige une classe nommée Plugin."""
    sans_classe = PLUGIN_VALIDE.replace("class Plugin(FrameFilter):",
                                        "class Autre(FrameFilter):")
    info = lire_metadonnees(ecrire(tmp_path, "sansclasse.py", sans_classe))

    assert charger_plugin(info) is None


def test_un_plugin_refuse_n_est_jamais_charge(tmp_path):
    """Un plugin marqué inutilisable ne doit pas voir son code
    s'exécuter, même si on demande son chargement."""
    futur = PLUGIN_VALIDE.replace("'api': 1", "'api': 99")
    info = lire_metadonnees(ecrire(tmp_path, "futur2.py", futur))

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


def test_liste_ignore_les_fichiers_prives(monkeypatch, tmp_path):
    """__init__.py et autres fichiers techniques ne sont pas des
    plugins."""
    from plugins import loader
    dossier = tmp_path / "plugins"
    dossier.mkdir()
    (dossier / "__init__.py").write_text(PLUGIN_VALIDE, encoding="utf-8")
    (dossier / "vrai.py").write_text(PLUGIN_VALIDE, encoding="utf-8")
    monkeypatch.setattr(loader, 'plugins_dir', lambda: dossier)
    monkeypatch.setattr(loader, 'extensions_dir',
                        lambda: tmp_path / "vide")

    trouves = lister_plugins()

    assert [p.identifiant for p in trouves] == ['vrai']


def test_api_version_est_exposee():
    """Les plugins déclarent la version du contrat qu'ils visent."""
    assert isinstance(API_VERSION, int)
    assert API_VERSION >= 1
