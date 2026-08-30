from pathlib import Path

from postprocess.subtitles_processor import (SubtitlesProcessor,
                                             whisper_is_available)
from ai.whisper_transcriber import WhisperTranscriber, SubtitleSegment


class FakeTranscriber:
    """Simule un WhisperTranscriber disponible avec 2 segments."""
    is_available = True

    def transcribe(self, audio_path, progress_callback=None):
        self.segments = [
            SubtitleSegment(0, 0.0, 2.0, "Bonjour"),
            SubtitleSegment(1, 2.5, 4.0, "Au revoir"),
        ]
        return True

    def export_srt(self, output_path):
        # Réutilise l'export réel pour produire un vrai SRT
        real = WhisperTranscriber.__new__(WhisperTranscriber)
        real.segments = self.segments
        return WhisperTranscriber.export_srt(real, output_path)


def test_produces_srt_next_to_video(tmp_path):
    video = tmp_path / "Lumina_test.mp4"
    video.write_bytes(b"fake")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    proc = SubtitlesProcessor(transcriber=FakeTranscriber())
    result = proc.run(str(video), str(audio), lambda p: None)

    assert result.success is True
    expected = tmp_path / "Lumina_test.srt"
    assert result.output_path == str(expected)
    content = expected.read_text(encoding="utf-8")
    assert "Bonjour" in content and "-->" in content


def test_fails_cleanly_without_audio(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    proc = SubtitlesProcessor(transcriber=FakeTranscriber())
    result = proc.run(str(video), None, lambda p: None)
    assert result.success is False
    assert result.error


def test_whisper_is_available_returns_bool():
    assert isinstance(whisper_is_available(), bool)
