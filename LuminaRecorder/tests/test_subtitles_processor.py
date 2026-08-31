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


class TranscriberSansParole(FakeTranscriber):
    """Transcription réussie mais vide : le VAD n'a rien retenu."""

    def transcribe(self, audio_path, progress_callback=None):
        self.segments = []
        return True


def test_aucune_parole_donne_un_message_honnete(tmp_path):
    """Constaté en usage réel : voix d'une seconde sur fond sonore, le
    VAD écarte tout, zéro segment. L'ancien message « Échec de l'export
    SRT » faisait croire à une panne du logiciel alors que Whisper n'a
    simplement entendu aucune parole."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")

    proc = SubtitlesProcessor(transcriber=TranscriberSansParole())
    result = proc.run(str(video), str(audio), lambda p: None)

    assert result.success is False
    assert "parole" in result.error.lower()
    assert not (tmp_path / "v.srt").exists()


class ModeleVadMuet:
    """Modèle faster-whisper simulé : muet avec VAD, parlant sans.

    Reproduit le cas réel qui a déclenché la seconde passe : le VAD
    écarte tout l'audio, la même transcription sans VAD trouve la
    parole."""

    class _Info:
        language = "fr"

    class _Segment:
        start, end, text = 0.0, 1.1, "Salut !"

    def transcribe(self, audio_path, language=None, beam_size=5,
                   vad_filter=True):
        if vad_filter:
            return iter([]), self._Info()
        return iter([self._Segment()]), self._Info()


def test_la_seconde_passe_sans_vad_rattrape_la_parole(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")

    t = WhisperTranscriber.__new__(WhisperTranscriber)
    t.language = None
    t.is_available = True
    t.whisper_lib = "faster-whisper"
    t.model = ModeleVadMuet()
    t.segments = []

    assert t.transcribe(str(audio)) is True
    assert len(t.segments) == 1
    assert t.segments[0].text == "Salut !"
