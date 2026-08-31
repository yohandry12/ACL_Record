"""Suppression optionnelle de l'original après une découpe réussie."""

import pytest

from postprocess.base import PostProcessResult
from postprocess.magic_cut_processor import MagicCutProcessor


def _resultat(success, output_path=None, error=None):
    return PostProcessResult(name="Magic Cut", success=success,
                             output_path=output_path, error=error)


def test_option_desactivee_par_defaut():
    assert MagicCutProcessor().delete_original is False


def test_original_supprime_apres_decoupe_reussie(tmp_path):
    original = tmp_path / "v.mp4"
    original.write_bytes(b"original")
    coupe = tmp_path / "v_cut.mp4"
    coupe.write_bytes(b"coupe")

    proc = MagicCutProcessor(delete_original=True)
    proc._cleanup_original(str(original), _resultat(True, str(coupe)))

    assert not original.exists()
    assert coupe.exists()


def test_original_conserve_si_option_desactivee(tmp_path):
    original = tmp_path / "v.mp4"
    original.write_bytes(b"original")
    coupe = tmp_path / "v_cut.mp4"
    coupe.write_bytes(b"coupe")

    MagicCutProcessor()._cleanup_original(str(original),
                                          _resultat(True, str(coupe)))
    assert original.exists()


def test_original_conserve_si_decoupe_echoue(tmp_path):
    """Jamais de suppression sur un échec : l'enregistrement serait perdu."""
    original = tmp_path / "v.mp4"
    original.write_bytes(b"original")

    proc = MagicCutProcessor(delete_original=True)
    proc._cleanup_original(str(original), _resultat(False, None, "erreur"))
    assert original.exists()


def test_original_conserve_si_rien_a_couper(tmp_path):
    """Succès sans fichier produit (aucun silence) : rien à supprimer."""
    original = tmp_path / "v.mp4"
    original.write_bytes(b"original")

    proc = MagicCutProcessor(delete_original=True)
    proc._cleanup_original(str(original),
                           _resultat(True, None, "Aucun silence à couper"))
    assert original.exists()


def test_original_conserve_si_coupe_absente_ou_vide(tmp_path):
    """La découpe dit avoir réussi mais le fichier est absent/vide :
    on ne supprime pas l'original sur la foi d'un statut."""
    original = tmp_path / "v.mp4"
    original.write_bytes(b"original")
    vide = tmp_path / "v_cut.mp4"
    vide.write_bytes(b"")

    proc = MagicCutProcessor(delete_original=True)
    proc._cleanup_original(str(original), _resultat(True, str(vide)))
    assert original.exists()

    vide.unlink()
    proc._cleanup_original(str(original), _resultat(True, str(vide)))
    assert original.exists()


def test_option_transmise_depuis_l_interface():
    """La case de l'interface doit atteindre le processeur."""
    from ui.main_window import AIOptions

    opts = {'privacy_blur': False, 'clean_canvas': False, 'overlay': False,
            'subtitles': False, 'magic_cut': True}

    procs = AIOptions.build_postprocessors(opts, "3 s", delete_original=True)
    assert procs[0].delete_original is True

    procs = AIOptions.build_postprocessors(opts, "3 s")
    assert procs[0].delete_original is False
