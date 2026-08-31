"""Post-processeur : sous-titres automatiques via Whisper → fichier .srt."""

import importlib.util
import os
from pathlib import Path
from typing import Callable, Optional

from ai.whisper_transcriber import WhisperTranscriber
from .base import PostProcessor, PostProcessResult


def whisper_is_available() -> bool:
    """True si faster-whisper ou whisper est installé (pour griser la case UI)."""
    return (importlib.util.find_spec("faster_whisper") is not None
            or importlib.util.find_spec("whisper") is not None)


class SubtitlesProcessor(PostProcessor):
    name = "Sous-titres"

    def __init__(self, model_size: str = "base",
                 language: Optional[str] = None, transcriber=None):
        self.model_size = model_size
        self.language = language
        self._transcriber = transcriber  # injection pour les tests

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if not audio_path or not os.path.exists(audio_path):
            return PostProcessResult(
                name=self.name, success=False,
                error="Pas de piste audio à transcrire")

        transcriber = self._transcriber or WhisperTranscriber(
            model_size=self.model_size, language=self.language)

        if not transcriber.is_available:
            return PostProcessResult(
                name=self.name, success=False,
                error="Whisper non installé (pip install faster-whisper)")

        progress_cb(0.1)
        if not transcriber.transcribe(audio_path,
                                      progress_callback=progress_cb):
            return PostProcessResult(name=self.name, success=False,
                                     error="Échec de la transcription")

        # Transcription réussie mais vide : dire la vérité. L'ancien
        # message « Échec de l'export SRT » laissait croire à une panne
        # alors que Whisper n'a simplement entendu aucune parole.
        if not getattr(transcriber, 'segments', None):
            return PostProcessResult(
                name=self.name, success=False,
                error="Aucune parole détectée dans l'enregistrement")

        srt_path = str(Path(video_path).with_suffix('.srt'))
        if not transcriber.export_srt(srt_path):
            return PostProcessResult(name=self.name, success=False,
                                     error="Échec de l'export SRT")

        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=srt_path)
