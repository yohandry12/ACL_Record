import shutil
import subprocess
import wave

import numpy as np
import pytest

import postprocess.magic_cut_processor as magic_cut_processor_module
from postprocess.magic_cut_processor import (MagicCutProcessor,
                                             build_ffmpeg_cut_command)

FFMPEG = shutil.which("ffmpeg")


def test_build_command_two_segments_with_audio():
    cmd = build_ffmpeg_cut_command(
        "ffmpeg", "in.mp4", [(0.0, 2.0), (3.0, 5.0)], "out.mp4",
        has_audio=True)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    assert "trim=start=0.0:end=2.0" in joined
    assert "atrim=start=3.0:end=5.0" in joined
    assert "concat=n=2:v=1:a=1" in joined
    assert cmd[-1] == "out.mp4"


def test_build_command_video_only():
    cmd = build_ffmpeg_cut_command(
        "ffmpeg", "in.mp4", [(0.0, 1.0)], "out.mp4", has_audio=False)
    joined = " ".join(cmd)
    assert "concat=n=1:v=1:a=0" in joined
    assert "atrim" not in joined


def _write_wav_with_silences(path, duration=10.0, rate=8000):
    """Signal 440 Hz avec silences à 2-3s, 5-6s, 7.5-8.5s (générateur du spec)."""
    t = np.linspace(0, duration, int(rate * duration))
    audio = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    audio[int(rate * 2):int(rate * 3)] = 0
    audio[int(rate * 5):int(rate * 6)] = 0
    audio[int(rate * 7.5):int(rate * 8.5)] = 0
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg absent du PATH")
def test_end_to_end_cut_shortens_video(tmp_path):
    # Vidéo synthétique 10 s (couleur unie) générée par FFmpeg
    video = tmp_path / "in.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x120:d=10", "-r", "10",
                    str(video)], check=True, capture_output=True)
    audio = tmp_path / "in.wav"
    _write_wav_with_silences(audio)

    proc = MagicCutProcessor(silence_threshold=0.02,
                             min_silence_duration=0.5,
                             max_silence_duration=3.0)
    result = proc.run(str(video), str(audio), lambda p: None)

    assert result.success is True
    out = tmp_path / "in_cut.mp4"
    assert result.output_path == str(out)
    probe = subprocess.run(
        [FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "quiet",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    assert duration < 9.0  # ~3 s de silences retirés sur 10 s


def test_no_silences_returns_success_without_output(tmp_path):
    """Audio plein signal : rien à couper, succès avec message, pas de fichier."""
    audio = tmp_path / "full.wav"
    rate = 8000
    t = np.linspace(0, 4.0, rate * 4)
    sig = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    with wave.open(str(audio), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(sig.tobytes())

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    proc = MagicCutProcessor()
    result = proc.run(str(video), str(audio), lambda p: None)
    assert result.success is True
    assert result.output_path is None  # rien coupé, original conservé


def test_probe_duration_reads_real_media(tmp_path):
    if FFMPEG is None:
        pytest.skip("FFmpeg absent")
    from postprocess.magic_cut_processor import _probe_duration
    video = tmp_path / "v.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=64x48:d=3", "-r", "10", str(video)],
                   check=True, capture_output=True)
    duration = _probe_duration(FFMPEG, str(video))
    assert duration is not None
    assert 2.8 < duration < 3.3


def test_probe_duration_returns_none_on_bad_file(tmp_path):
    if FFMPEG is None:
        pytest.skip("FFmpeg absent")
    from postprocess.magic_cut_processor import _probe_duration
    bad = tmp_path / "pasunevideo.mp4"
    bad.write_bytes(b"nimporte quoi")
    assert _probe_duration(FFMPEG, str(bad)) is None


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg absent du PATH")
def test_long_silence_cut_when_threshold_raised(tmp_path):
    """Avec un seuil élevé, les temps de navigation sont supprimés."""
    video = tmp_path / "in.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x120:d=20", "-r", "10", str(video)],
                   check=True, capture_output=True)

    # 12 s de navigation silencieuse, puis 8 s de son
    audio = tmp_path / "in.wav"
    rate = 8000
    t = np.linspace(0, 8.0, rate * 8)
    voix = (np.sin(2 * np.pi * 200 * t) * 12000).astype(np.int16)
    signal = np.concatenate([np.zeros(rate * 12, dtype=np.int16), voix])
    with wave.open(str(audio), 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
        wf.writeframes(signal.tobytes())

    proc = MagicCutProcessor(silence_threshold=0.02,
                             min_silence_duration=0.5,
                             max_silence_duration=float('inf'))
    result = proc.run(str(video), str(audio), lambda p: None)
    assert result.success is True

    out = tmp_path / "in_cut.mp4"
    probe = subprocess.run(
        [FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    assert duration < 12.0   # les 12 s de navigation ont sauté


def _run_with_stubbed_ffmpeg(monkeypatch, tmp_path, video_duration):
    """Exécute MagicCutProcessor.run() en simulant FFmpeg : capture les
    segments réellement passés à build_ffmpeg_cut_command sans exécuter
    de vrai encodage (I3 : vérifie uniquement la logique de mise à
    l'échelle du ratio)."""
    audio = tmp_path / "in.wav"
    _write_wav_with_silences(audio, duration=10.0)  # silences à 2-3,5-6,7.5-8.5s
    video = tmp_path / "in.mp4"
    video.write_bytes(b"fake")

    monkeypatch.setattr(magic_cut_processor_module, "_probe_duration",
                        lambda ffmpeg, path: video_duration)
    monkeypatch.setattr(
        magic_cut_processor_module.VideoEncoder, "_find_ffmpeg",
        lambda self: "ffmpeg")

    captured = {}
    real_build = magic_cut_processor_module.build_ffmpeg_cut_command

    def spy_build(ffmpeg, input_path, segments, output_path, has_audio):
        captured["segments"] = segments
        return real_build(ffmpeg, input_path, segments, output_path,
                          has_audio)

    monkeypatch.setattr(magic_cut_processor_module, "build_ffmpeg_cut_command",
                        spy_build)

    class FakeCompleted:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: FakeCompleted())

    proc = MagicCutProcessor(silence_threshold=0.02,
                             min_silence_duration=0.5,
                             max_silence_duration=3.0)
    result = proc.run(str(video), str(audio), lambda p: None)
    assert result.success is True
    return captured["segments"]


def test_ratio_out_of_range_leaves_segments_unchanged(monkeypatch, tmp_path):
    """I3 : ratio hors plage plausible (ex. son système avec
    amix duration=longest, vidéo bien plus longue que le micro) ->
    on ne redimensionne pas, les segments gardent la durée du WAV."""
    audio = tmp_path / "in.wav"
    _write_wav_with_silences(audio, duration=10.0)

    from postprocess.magic_cut_processor import _segments_excluding_silences
    from ai.magic_cut import MagicCutEngine
    engine = MagicCutEngine(silence_threshold=0.02, min_silence_duration=0.5,
                            max_silence_duration=3.0)
    engine.load_audio_file(str(audio))
    silences = engine.detect_silences()
    expected_unscaled = _segments_excluding_silences(engine.duration, silences)

    # Vidéo 2x plus longue que le WAV micro -> ratio ~= 2.0, hors (0.8, 1.25)
    segments = _run_with_stubbed_ffmpeg(monkeypatch, tmp_path,
                                        video_duration=engine.duration * 2.0)

    assert segments == expected_unscaled


def test_ratio_within_range_scales_segments(monkeypatch, tmp_path):
    """I3 : ratio plausible (léger décalage fps réel / -shortest) ->
    les segments sont bien mis à l'échelle."""
    audio = tmp_path / "in.wav"
    _write_wav_with_silences(audio, duration=10.0)

    from postprocess.magic_cut_processor import _segments_excluding_silences
    from ai.magic_cut import MagicCutEngine
    engine = MagicCutEngine(silence_threshold=0.02, min_silence_duration=0.5,
                            max_silence_duration=3.0)
    engine.load_audio_file(str(audio))
    silences = engine.detect_silences()
    unscaled = _segments_excluding_silences(engine.duration, silences)

    ratio = 1.1  # dans (0.8, 1.25)
    video_duration = engine.duration * ratio
    expected = [(s * ratio, min(e * ratio, video_duration))
                for s, e in unscaled if s * ratio < video_duration]

    segments = _run_with_stubbed_ffmpeg(monkeypatch, tmp_path,
                                        video_duration=video_duration)

    assert segments != unscaled
    assert segments == expected
