"""Le worker de post-traitement doit toujours nettoyer et rendre la main."""

import os

import pytest

from postprocess.base import PostProcessor, PostProcessResult, run_postprocessors


class ProcesseurQuiPlante(PostProcessor):
    name = "plante"

    def run(self, video_path, audio_path, progress_cb):
        raise RuntimeError("boom")


def simuler_worker(processors, video_path, audio_path, after):
    """Reproduit la logique de MainWindow._run_postprocessing.worker()."""
    results = []
    try:
        results = run_postprocessors(processors, video_path, audio_path,
                                     lambda p: None)
    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        after(results)


def test_keep_wav_supprime_et_resume_affiche(tmp_path):
    keep = tmp_path / "audio.keep.wav"
    keep.write_bytes(b"fake")
    affiches = []

    simuler_worker([ProcesseurQuiPlante()], "v.mp4", str(keep),
                   affiches.append)

    assert not keep.exists()          # la copie temporaire est nettoyée
    assert len(affiches) == 1         # le résumé est affiché malgré l'échec
    assert affiches[0][0].success is False


def test_resume_affiche_meme_sans_audio(tmp_path):
    affiches = []
    simuler_worker([], "v.mp4", None, affiches.append)
    assert affiches == [[]]
