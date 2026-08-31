"""
Post-processeur Magic Cut : détecte les silences (MagicCutEngine) et
produit une vidéo raccourcie via FFmpeg (trim/atrim + concat).
Le fichier original n'est jamais modifié : sortie dans <nom>_cut.mp4.
"""

import os
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ai.magic_cut import MagicCutEngine, SilenceSegment
from core.encoder import VideoEncoder
from .base import PostProcessor, PostProcessResult


def _probe_duration(ffmpeg: str, path: str) -> Optional[float]:
    """Durée réelle d'un média, via ffprobe (None si indisponible)."""
    ffprobe = ffmpeg.replace('ffmpeg', 'ffprobe')
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=nw=1:nk=1', path],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def _segments_excluding_silences(
        duration: float, silences: List[SilenceSegment]
        ) -> List[Tuple[float, float]]:
    """Segments à garder = [0, duration] privé des silences à couper.

    `MagicCutEngine.get_trimmed_segments()` renvoie des segments qui se
    touchent bout à bout (les silences ne sont pas réellement retirés) ;
    on reconstruit donc ici les segments à conserver directement à partir
    des silences détectés, sans modifier le moteur.
    """
    cuts = sorted(
        ((s.start_time, s.end_time) for s in silences if s.should_cut),
        key=lambda c: c[0])

    segments = []
    cursor = 0.0
    for start, end in cuts:
        if start > cursor:
            segments.append((cursor, start))
        cursor = max(cursor, end)
    if duration > cursor:
        segments.append((cursor, duration))

    return segments


def build_ffmpeg_cut_command(ffmpeg: str, input_path: str,
                             segments: List[Tuple[float, float]],
                             output_path: str,
                             has_audio: bool) -> List[str]:
    """Construit la commande FFmpeg concaténant les segments à garder."""
    parts = []
    for i, (start, end) in enumerate(segments):
        parts.append(f"[0:v]trim=start={start}:end={end},"
                     f"setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={start}:end={end},"
                         f"asetpts=PTS-STARTPTS[a{i}]")

    n = len(segments)
    if has_audio:
        inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{inputs}concat=n={n}:v=1:a=1[outv][outa]")
        maps = ["-map", "[outv]", "-map", "[outa]"]
    else:
        inputs = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{inputs}concat=n={n}:v=1:a=0[outv]")
        maps = ["-map", "[outv]"]

    return [ffmpeg, "-y", "-i", input_path,
            "-filter_complex", ";".join(parts)] + maps + [output_path]


class MagicCutProcessor(PostProcessor):
    name = "Magic Cut"

    def __init__(self, silence_threshold: float = 0.02,
                 min_silence_duration: float = 0.5,
                 max_silence_duration: float = 3.0,
                 delete_original: bool = False):
        self.silence_threshold = silence_threshold
        self.min_silence_duration = min_silence_duration
        self.max_silence_duration = max_silence_duration
        # Désactivé par défaut : la découpe est irréversible, l'original
        # est la seule sauvegarde si Magic Cut coupe un passage voulu
        self.delete_original = delete_original

    def _cleanup_original(self, video_path: str,
                          result: PostProcessResult) -> None:
        """Supprime l'enregistrement complet si l'utilisateur l'a demandé.

        Uniquement quand la découpe a réellement produit un fichier non
        vide : un statut de succès ne suffit pas à justifier la
        destruction de l'original.
        """
        if not self.delete_original or not result.success:
            return
        if not result.output_path or not os.path.exists(result.output_path):
            return
        if os.path.getsize(result.output_path) == 0:
            return

        try:
            os.remove(video_path)
            print(f"[Lumina] Original supprimé: {video_path}")
        except OSError as e:
            print(f"[Lumina] Impossible de supprimer l'original: {e}")

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if not audio_path or not os.path.exists(audio_path):
            return PostProcessResult(
                name=self.name, success=False,
                error="Pas de piste audio pour détecter les silences")

        engine = MagicCutEngine(
            silence_threshold=self.silence_threshold,
            min_silence_duration=self.min_silence_duration,
            max_silence_duration=self.max_silence_duration)

        if not engine.load_audio_file(audio_path):
            return PostProcessResult(name=self.name, success=False,
                                     error="Impossible de lire l'audio")
        progress_cb(0.2)

        silences = engine.detect_silences()
        if not silences:
            return PostProcessResult(name=self.name, success=True,
                                     output_path=None,
                                     error="Aucun silence à couper")
        progress_cb(0.4)

        segments = _segments_excluding_silences(engine.duration, silences)
        if not segments or len(segments) == 0:
            return PostProcessResult(name=self.name, success=True,
                                     output_path=None,
                                     error="Aucun segment à conserver")

        try:
            ffmpeg = VideoEncoder()._find_ffmpeg()
        except FileNotFoundError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=str(e))

        # Les silences sont mesurés sur le WAV brut, les coupes appliquées
        # à la vidéo encodée : leurs durées diffèrent (fps réel, -shortest,
        # latence de démarrage). Sans remise à l'échelle, chaque coupe
        # décale le son un peu plus.
        video_duration = _probe_duration(ffmpeg, video_path)
        if video_duration and engine.duration and engine.duration > 0.1:
            ratio = video_duration / engine.duration
            # Un ratio hors de cette plage signale que les deux pistes ne
            # décrivent pas la même chose (ex. amix duration=longest avec
            # le son système) : mieux vaut ne pas redimensionner que
            # d'étirer les coupes.
            if 0.8 < ratio < 1.25 and abs(ratio - 1.0) > 0.01:
                segments = [(s * ratio, e * ratio) for s, e in segments]
                segments = [(s, min(e, video_duration)) for s, e in segments
                            if s < video_duration]

        output_path = str(Path(video_path).with_name(
            Path(video_path).stem + "_cut.mp4"))
        # La vidéo finale (post-fusion) contient l'audio
        cmd = build_ffmpeg_cut_command(ffmpeg, video_path, segments,
                                       output_path, has_audio=True)
        progress_cb(0.5)

        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=3600)
        if proc.returncode != 0:
            # Retente sans piste audio (vidéo sans son)
            cmd = build_ffmpeg_cut_command(ffmpeg, video_path, segments,
                                           output_path, has_audio=False)
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=3600)
            if proc.returncode != 0:
                return PostProcessResult(
                    name=self.name, success=False,
                    error=f"FFmpeg a échoué: {proc.stderr[-300:]}")

        progress_cb(1.0)
        result = PostProcessResult(name=self.name, success=True,
                                   output_path=output_path)
        self._cleanup_original(video_path, result)
        return result
