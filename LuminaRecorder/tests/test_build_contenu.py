"""Ce que le script de build embarque dans l'application.

Ces tests lisent build_installer.bat sans rien construire : un build
complet prend plusieurs minutes, mais une erreur d'inclusion se voit
dans le script. Ils existent parce qu'une vidéo de diagnostic de 27 Mo
laissée dans assets/ a fait passer le setup de 118,8 à 145,6 Mo sans
qu'aucun signal ne le dise — la taille du socle est une promesse faite
à l'utilisateur, pas un détail.
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).parent.parent
SCRIPT = RACINE / "build_installer.bat"

# Ce qu'on ne veut jamais voir entrer dans l'exécutable, quelle que
# soit sa provenance : ce sont des enregistrements, pas des ressources
EXTENSIONS_LOURDES = ('.mp4', '.avi', '.mjpeg', '.mkv', '.mov', '.wav',
                      '.srt', '.zip')


def _inclusions():
    """Les paires (source, destination) des --add-data du script."""
    texte = SCRIPT.read_text(encoding='utf-8', errors='replace')
    paires = []
    for brut in re.findall(r'--add-data\s+"([^"]+)"', texte):
        source, _, destination = brut.partition(';')
        paires.append((source.strip(), destination.strip()))
    return paires


def test_le_script_de_build_existe():
    assert SCRIPT.is_file()
    assert _inclusions(), "aucun --add-data trouvé : format du script changé ?"


def test_assets_n_est_pas_embarque_en_bloc():
    """assets/ reçoit aussi les enregistrements de l'utilisateur.

    L'embarquer entier fait entrer dans le setup tout ce qui traîne
    dans ce dossier — vidéos de test, exports, captures.
    """
    sources = {s.replace('\\', '/').rstrip('/') for s, _ in _inclusions()}

    assert 'assets' not in sources, (
        "assets/ embarqué en bloc : tout enregistrement présent dans ce "
        "dossier gonflera le setup")


def test_les_dossiers_embarques_existent():
    """Un chemin fautif ferait échouer le build, ou pire : passerait
    silencieusement et l'application manquerait sa ressource."""
    for source, _ in _inclusions():
        chemin = RACINE / source.replace('\\', '/')
        assert chemin.exists(), f"{source} n'existe pas"


def test_aucun_fichier_lourd_dans_ce_qui_est_embarque():
    """Le contenu réel des dossiers inclus, pas seulement leur nom."""
    coupables = []
    for source, _ in _inclusions():
        dossier = RACINE / source.replace('\\', '/')
        if not dossier.is_dir():
            continue
        for fichier in dossier.rglob('*'):
            if fichier.is_file() and \
                    fichier.suffix.lower() in EXTENSIONS_LOURDES:
                coupables.append(f"{fichier.relative_to(RACINE)} "
                                 f"({fichier.stat().st_size // 1048576} Mo)")

    assert not coupables, (
        "fichiers lourds dans le périmètre du build :\n  "
        + "\n  ".join(coupables))


def test_les_ressources_utilisees_par_l_application_sont_incluses():
    """L'inverse du test précédent : restreindre le périmètre ne doit
    pas priver l'application de ce dont elle a besoin."""
    inclus = {s.replace('\\', '/').rstrip('/') for s, _ in _inclusions()}

    for requis in ('assets/icons', 'assets/Records_examples', 'config',
                   'src'):
        assert any(i == requis or i.startswith(requis + '/')
                   or requis.startswith(i + '/') for i in inclus), \
            f"{requis} n'est plus embarqué"


def test_les_paquets_ia_restent_exclus():
    """Le socle allégé repose sur ces exclusions : sans elles,
    PyInstaller réaspire PyTorch par les imports gardés et le setup
    repasse à 1 Go."""
    texte = SCRIPT.read_text(encoding='utf-8', errors='replace')

    for module in ('torch', 'easyocr', 'faster_whisper', 'ctranslate2'):
        assert f'--exclude-module={module}' in texte, \
            f"{module} n'est plus exclu du build"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
