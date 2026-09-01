"""Les exemples doivent rester valides : ils sont la documentation.

Un développeur tiers copie ces fichiers pour écrire son propre plugin.
S'ils cessent de refléter le contrat réel, ils enseignent une erreur —
d'où ces tests, qui les font vivre au même rythme que le code.
"""

from pathlib import Path

import numpy as np
import pytest

from filters.base import FilterChain, FrameFilter
from postprocess.base import PostProcessor
from plugins.loader import API_VERSION, charger_plugin, lire_metadonnees

DOSSIER = Path(__file__).parent.parent / "exemples_plugins"


def _exemples():
    return sorted(DOSSIER.glob("*.py"))


def test_les_exemples_sont_des_plugins_valides():
    fichiers = _exemples()
    assert fichiers, "aucun exemple trouvé"

    for f in fichiers:
        info = lire_metadonnees(str(f))
        assert info is not None, f"{f.name} n'est pas reconnu"
        assert info.utilisable, f"{f.name} : {info.erreur}"
        # Un exemple qui déclarerait une API future serait refusé par
        # Lumina : il enseignerait au lecteur une erreur silencieuse
        assert info.api == API_VERSION, f"{f.name} : contrat périmé"


def test_chaque_exemple_expose_une_classe_plugin():
    """Sans classe Plugin, le chargeur retourne None sans rien dire."""
    for f in _exemples():
        info = lire_metadonnees(str(f))
        instance = charger_plugin(info)
        assert instance is not None, f"{f.name} : classe Plugin absente"
        assert isinstance(instance, (FrameFilter, PostProcessor)), (
            f"{f.name} : n'implémente aucun des deux contrats")


def test_le_filigrane_traite_une_image():
    info = lire_metadonnees(str(DOSSIER / "filigrane.py"))
    plugin = charger_plugin(info)
    image = np.zeros((120, 160, 3), dtype=np.uint8)

    sortie = plugin.process(image)

    assert sortie.shape == image.shape
    assert sortie.dtype == image.dtype
    # Le filigrane doit être visible : une image restée noire signifie
    # que le texte est tombé hors cadre
    assert sortie.max() > 0, "aucun pixel écrit"


def test_le_filigrane_suit_la_resolution():
    """À taille fixe, le filigrane serait illisible en 4K.

    Mesuré : une taille codée en dur couvre le même nombre de pixels en
    1366x768 qu'en 3840x2160. L'exemple doit montrer l'échelle
    proportionnelle, sinon il enseigne le défaut.
    """
    info = lire_metadonnees(str(DOSSIER / "filigrane.py"))
    plugin = charger_plugin(info)

    def couverture(largeur, hauteur):
        image = np.zeros((hauteur, largeur, 3), dtype=np.uint8)
        return int(plugin.process(image).sum())

    petit = couverture(1366, 768)
    grand = couverture(3840, 2160)

    assert petit > 0, "filigrane invisible"
    assert grand > petit * 2, (
        f"filigrane presque fixe : {petit} -> {grand}")


def test_l_horodatage_ecrit_sur_chaque_image():
    info = lire_metadonnees(str(DOSSIER / "horodatage.py"))
    plugin = charger_plugin(info)
    image = np.zeros((200, 320, 3), dtype=np.uint8)

    sortie = plugin.process(image)

    assert sortie.shape == image.shape
    assert sortie.max() > 0


def test_les_filtres_exemples_tiennent_le_budget_temps_reel():
    """Un filtre trop lent est désactivé : l'exemple ne doit pas l'être.

    Budget de 33 ms = 30 images/s. Un exemple qui le dépasserait
    s'éteindrait tout seul chez l'utilisateur, sans qu'il comprenne
    pourquoi.
    """
    filtres = []
    for f in _exemples():
        instance = charger_plugin(lire_metadonnees(str(f)))
        if isinstance(instance, FrameFilter):
            filtres.append(instance)
    assert filtres, "aucun filtre parmi les exemples"

    chaine = FilterChain(filtres, frame_budget=0.033, max_slow_frames=5)
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for _ in range(10):
        image = chaine.process(image)

    assert chaine.active_count == len(filtres), "un exemple a été désactivé"


def test_le_gif_est_un_post_traitement():
    info = lire_metadonnees(str(DOSSIER / "gif.py"))
    plugin = charger_plugin(info)

    assert isinstance(plugin, PostProcessor)
    assert not isinstance(plugin, FrameFilter), (
        "un post-traitement dans la chaîne temps réel bloquerait la capture")


def test_le_gif_signale_son_echec_sans_lever(tmp_path):
    """Contrat des post-traitements : jamais d'exception, un résultat.

    Une exception ici perdrait les résultats des traitements suivants.
    """
    info = lire_metadonnees(str(DOSSIER / "gif.py"))
    plugin = charger_plugin(info)
    inexistant = str(tmp_path / "absent.mp4")

    resultat = plugin.run(inexistant, None, lambda p: None)

    assert resultat.success is False
    assert resultat.error, "un échec doit être expliqué"


def test_les_exemples_ne_sont_pas_charges_au_demarrage():
    """Le dossier d'exemples n'est pas le dossier des plugins actifs.

    Ces fichiers sont de la documentation à copier, pas des plugins
    installés : Lumina ne doit pas les exécuter tout seul.
    """
    from plugins.loader import extensions_dir, plugins_dir

    assert DOSSIER.resolve() != plugins_dir().resolve()
    assert DOSSIER.resolve() != extensions_dir().resolve()


def test_le_readme_documente_les_deux_contrats():
    readme = (DOSSIER / "README.md").read_text(encoding="utf-8")

    for attendu in ("LUMINA_PLUGIN", "FrameFilter", "PostProcessor",
                    "api", "Plugin"):
        assert attendu in readme, f"README muet sur {attendu}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
