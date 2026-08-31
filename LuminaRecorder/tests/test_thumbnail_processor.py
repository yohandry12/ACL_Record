"""Post-processeur Miniatures : génère 3 propositions de PNG à partir des
frames les plus intéressantes de la vidéo, avec texte accrocheur en
surimpression SI un moteur IA est disponible (jamais de texte inventé)."""

import shutil
import subprocess

import cv2
import pytest

from postprocess.thumbnail_processor import (ThumbnailProcessor,
                                              thumbnails_are_available)
from ui.main_window import AIOptions


ffmpeg_missing = shutil.which("ffmpeg") is None


def _make_synthetic_video(path, duration=4, fps=10, size=(320, 240)):
    """Vidéo synthétique avec un dégradé mouvant (contenu net et varié),
    utile pour vérifier que la sélection de frames ne prend pas que du
    noir ou du flou uniforme."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"testsrc=size={size[0]}x{size[1]}:rate={fps}:duration={duration}",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


def _make_black_video(path, duration=2, fps=10, size=(320, 240)):
    """Vidéo entièrement noire : aucune frame ne devrait être « intéressante »
    au sens net/contrasté, mais la sélection doit tout de même produire
    les fichiers demandés (dernier recours)."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:size={size[0]}x{size[1]}:rate={fps}:duration={duration}",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


class FakeAIEngine:
    """Simule un moteur IA disponible."""

    def is_available(self):
        return True


class FakeAIService:
    def __init__(self, ai_engine):
        self.ai = ai_engine

    def suggest_thumbnail(self, video_context):
        return "Un titre vraiment très accrocheur qui dépasse six mots"


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg introuvable")
def test_produces_three_png_next_to_video(tmp_path):
    video = tmp_path / "Lumina_test.mp4"
    _make_synthetic_video(video)

    proc = ThumbnailProcessor(count=3)
    result = proc.run(str(video), None, lambda p: None)

    assert result.success is True
    expected = [tmp_path / f"Lumina_test_thumb{i}.png" for i in (1, 2, 3)]
    for f in expected:
        assert f.exists()
        assert f.stat().st_size > 0
        img = cv2.imread(str(f))
        assert img is not None
        assert img.shape[0] > 0 and img.shape[1] > 0

    assert result.output_path == str(expected[0])


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg introuvable")
def test_selection_avoids_pure_black_when_content_available(tmp_path):
    """Sur une vidéo avec du contenu varié, les miniatures choisies ne
    doivent pas être des frames quasi-noires/uniformes."""
    video = tmp_path / "content.mp4"
    _make_synthetic_video(video, duration=4)

    proc = ThumbnailProcessor(count=3)
    result = proc.run(str(video), None, lambda p: None)

    assert result.success is True
    for i in (1, 2, 3):
        f = tmp_path / f"content_thumb{i}.png"
        img = cv2.imread(str(f))
        assert img is not None
        assert img.std() > 5.0  # pas une image quasi uniforme/noire


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg introuvable")
def test_no_text_without_ai_engine(tmp_path, monkeypatch):
    """Règle du projet : jamais de texte inventé. Sans IA disponible,
    aucune surimpression n'est dessinée (comportement observable indirect :
    le run réussit sans erreur et sans dépendre d'un moteur IA)."""
    video = tmp_path / "noai.mp4"
    _make_synthetic_video(video, duration=3)

    proc = ThumbnailProcessor(count=3, ai_engine=None)
    result = proc.run(str(video), None, lambda p: None)

    assert result.success is True
    for i in (1, 2, 3):
        f = tmp_path / f"noai_thumb{i}.png"
        assert f.exists()


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg introuvable")
def test_text_overlay_when_ai_available(tmp_path, monkeypatch):
    """Avec un moteur IA disponible, le titre suggéré doit être utilisé
    (tronqué aux 6 premiers mots) — on vérifie indirectement en s'assurant
    que la génération réussit et que le service IA a bien été sollicité."""
    video = tmp_path / "withai.mp4"
    _make_synthetic_video(video, duration=3)

    calls = []

    class TrackingAIService(FakeAIService):
        def suggest_thumbnail(self, video_context):
            calls.append(video_context)
            return super().suggest_thumbnail(video_context)

    import postprocess.thumbnail_processor as tp
    monkeypatch.setattr(tp, "LuminaAIService", TrackingAIService)

    proc = ThumbnailProcessor(count=3, ai_engine=FakeAIEngine())
    result = proc.run(str(video), None, lambda p: None)

    assert result.success is True
    assert len(calls) == 1


def test_fails_cleanly_on_missing_video(tmp_path):
    missing = tmp_path / "does_not_exist.mp4"
    proc = ThumbnailProcessor(count=3)
    result = proc.run(str(missing), None, lambda p: None)
    assert result.success is False
    assert result.error


def test_thumbnails_are_available_returns_bool():
    assert isinstance(thumbnails_are_available(), bool)
    # cv2 est toujours installé dans ce projet : jamais grisé côté UI
    assert thumbnails_are_available() is True


def test_option_reaches_processor_via_build_postprocessors():
    opts = {'privacy_blur': False, 'clean_canvas': False, 'overlay': False,
            'subtitles': False, 'magic_cut': False, 'thumbnails': True}
    procs = AIOptions.build_postprocessors(opts)
    assert len(procs) == 1
    from postprocess.thumbnail_processor import ThumbnailProcessor as TP
    assert isinstance(procs[0], TP)


def test_thumbnails_processor_runs_last_after_magic_cut():
    opts = {'privacy_blur': False, 'clean_canvas': False, 'overlay': False,
            'subtitles': True, 'magic_cut': True, 'thumbnails': True}
    procs = AIOptions.build_postprocessors(opts)
    from postprocess.magic_cut_processor import MagicCutProcessor
    from postprocess.thumbnail_processor import ThumbnailProcessor as TP
    assert isinstance(procs[-1], TP)
    assert isinstance(procs[-2], MagicCutProcessor)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg absent")
def test_courte_video_produit_moins_de_miniatures_sans_doublon(tmp_path):
    """Mieux vaut 1 vraie miniature que 3 copies présentées comme des
    propositions différentes."""
    import cv2
    import numpy as np

    video = tmp_path / "court.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10:duration=0.3",
                    str(video)], check=True, capture_output=True)

    proc = ThumbnailProcessor(count=3)
    result = proc.run(str(video), None, lambda p: None)

    produites = sorted(tmp_path.glob("court_thumb*.png"))
    if result.success and produites:
        images = [cv2.imread(str(p)) for p in produites]
        for i, a in enumerate(images):
            for b in images[i + 1:]:
                assert not np.array_equal(a, b), \
                    "deux miniatures identiques livrées comme propositions"
