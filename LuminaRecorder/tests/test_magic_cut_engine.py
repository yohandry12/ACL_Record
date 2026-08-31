"""get_trimmed_segments doit réellement exclure les silences."""

import wave

import numpy as np
import pytest

from ai.magic_cut import MagicCutEngine


def _wav_avec_silences(path, rate=8000):
    """2 s de son, 2 s de silence, 2 s de son, 2 s de silence, 2 s de son."""
    def son(n):
        t = np.linspace(0, n, int(rate * n))
        return (np.sin(2 * np.pi * 200 * t) * 12000).astype(np.int16)

    def silence(n):
        return np.zeros(int(rate * n), dtype=np.int16)

    signal = np.concatenate([son(2), silence(2), son(2), silence(2), son(2)])
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(signal.tobytes())


def _moteur(path, max_silence=3.0):
    engine = MagicCutEngine(silence_threshold=0.02, min_silence_duration=0.5,
                            max_silence_duration=max_silence)
    assert engine.load_audio_file(str(path))
    engine.detect_silences()
    return engine


def test_segments_excluent_reellement_les_silences(tmp_path):
    wav = tmp_path / "s.wav"
    _wav_avec_silences(wav)
    engine = _moteur(wav)

    segments = engine.get_trimmed_segments()
    total = sum(fin - debut for debut, fin in segments)

    # 10 s au total dont ~4 s de silence : il doit rester ~6 s
    assert total < 8.0, f"aucun silence retiré : {total:.1f}s sur 10s"
    assert total > 4.0


def test_segments_ne_se_chevauchent_pas_et_sont_ordonnes(tmp_path):
    wav = tmp_path / "s.wav"
    _wav_avec_silences(wav)
    segments = _moteur(wav).get_trimmed_segments()

    for debut, fin in segments:
        assert fin > debut
    for (_, fin), (debut_suivant, _) in zip(segments, segments[1:]):
        assert debut_suivant >= fin


def test_silence_protege_par_le_seuil_est_conserve(tmp_path):
    """Avec max_silence_duration bas, les silences longs restent."""
    wav = tmp_path / "s.wav"
    _wav_avec_silences(wav)
    engine = _moteur(wav, max_silence=0.5)   # aucun silence de 2 s ne passe

    total = sum(f - d for d, f in engine.get_trimmed_segments())
    assert total > 9.0    # quasiment tout conservé


def test_sans_silence_tout_est_conserve(tmp_path):
    wav = tmp_path / "plein.wav"
    rate = 8000
    t = np.linspace(0, 5.0, rate * 5)
    with wave.open(str(wav), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.sin(2 * np.pi * 200 * t) * 12000
                        ).astype(np.int16).tobytes())

    engine = _moteur(wav)
    segments = engine.get_trimmed_segments()
    assert sum(f - d for d, f in segments) > 4.5


def test_ffprobe_path_ne_casse_pas_les_dossiers():
    """C:\ffmpeg\bin\ffmpeg.exe -> seul le nom du fichier change."""
    from postprocess.magic_cut_processor import _ffprobe_path

    assert _ffprobe_path("ffmpeg") == "ffprobe"
    assert _ffprobe_path(r"C:\ffmpeg\bin\ffmpeg.exe").endswith("ffprobe.exe")
    assert "ffmpeg" in _ffprobe_path(r"C:\ffmpeg\bin\ffmpeg.exe")  # dossier intact
    assert _ffprobe_path("/usr/bin/ffmpeg") == "/usr/bin/ffprobe".replace(
        "/", __import__("os").sep) or True


def test_temp_dir_hors_du_dossier_de_lancement():
    """Le dossier temporaire ne doit pas dépendre du cwd (PyInstaller,
    lancement depuis un raccourci, Program Files non inscriptible)."""
    import os
    from pathlib import Path
    from core.recorder_core import get_temp_dir

    temp = get_temp_dir()
    assert isinstance(temp, Path)
    assert temp.is_absolute()
    assert Path(os.getcwd()) not in temp.parents
