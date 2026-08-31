"""Post-processeur : génère 3 propositions de miniatures (PNG) à partir des
frames les plus intéressantes de la vidéo, avec texte accrocheur en
surimpression SI un moteur IA est disponible.

Règle du projet : ne jamais faire croire à une fonctionnalité active. Sans
moteur IA disponible, aucun texte n'est inventé — les miniatures sont
produites sans surimpression. La génération d'images ne dépend pas de l'IA
(cv2 suffit), donc `thumbnails_are_available()` est toujours True et la case
UI n'a pas de raison d'être grisée.
"""

import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from services.ai_engine import LuminaAIEngine, LuminaAIService
from .base import PostProcessor, PostProcessResult


def thumbnails_are_available() -> bool:
    """True si cv2 est importable. La génération de miniatures fonctionne
    sans IA (juste sans texte en surimpression) : cette case n'est donc
    jamais grisée dans l'UI, contrairement aux sous-titres (Whisper) ou au
    flou de confidentialité (OCR)."""
    return True


def _sample_positions(frame_count: int, samples: int = 40) -> List[int]:
    """~`samples` indices de frames répartis sur toute la vidéo."""
    if frame_count <= 0:
        return []
    n = min(samples, frame_count)
    if n <= 1:
        return [0]
    step = (frame_count - 1) / (n - 1)
    return sorted({int(round(i * step)) for i in range(n)})


def _sharpness(gray: np.ndarray) -> float:
    """Variance du laplacien : plus c'est élevé, plus l'image est nette."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _is_low_content(gray: np.ndarray, variance_threshold: float = 60.0) -> bool:
    """True si la frame est quasi-noire/uniforme (variance de luminance
    trop faible pour être une bonne miniature)."""
    return float(gray.var()) < variance_threshold


def _score_frame(frame: np.ndarray) -> Tuple[bool, float]:
    """Retourne (contenu_suffisant, score_netteté)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    low_content = _is_low_content(gray)
    return (not low_content, _sharpness(gray))


def _pick_spread_indices(candidate_positions: List[int], count: int) -> List[int]:
    """Choisit `count` positions réparties dans la liste triée de positions
    candidates (par frame index), pour éviter 3 miniatures presque
    identiques prises à quelques images d'écart."""
    if not candidate_positions:
        return []
    candidate_positions = sorted(candidate_positions)
    if len(candidate_positions) <= count:
        return candidate_positions
    step = (len(candidate_positions) - 1) / (count - 1) if count > 1 else 0
    return [candidate_positions[int(round(i * step))] for i in range(count)]


def _draw_caption(frame: np.ndarray, text: str) -> np.ndarray:
    """Dessine `text` en surimpression : fond semi-transparent sombre,
    texte blanc, taille proportionnelle à la largeur de l'image."""
    if not text:
        return frame

    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = max(0.5, w / 700.0)
    thickness = max(1, int(round(font_scale * 2)))

    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale,
                                                  thickness)
    margin = int(round(font_scale * 12))
    band_h = text_h + baseline + margin * 2
    band_top = max(0, h - band_h)

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, band_top), (w, h), (0, 0, 0), thickness=-1)
    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

    text_x = margin
    text_y = h - margin - baseline
    cv2.putText(frame, text, (text_x, text_y), font, font_scale,
               (255, 255, 255), thickness, cv2.LINE_AA)
    return frame


def _first_six_words(text: str) -> str:
    words = text.strip().split()
    return " ".join(words[:6])


class ThumbnailProcessor(PostProcessor):
    name = "Miniatures"

    def __init__(self, count: int = 3, ai_engine: Optional[LuminaAIEngine] = None):
        self.count = count
        self.ai_engine = ai_engine

    def _suggest_caption(self, video_path: str) -> str:
        """Titre court (<= 6 mots) via l'IA si disponible, sinon chaîne
        vide (jamais de texte inventé)."""
        if not self.ai_engine:
            return ""
        try:
            if not self.ai_engine.is_available():
                return ""
            service = LuminaAIService(self.ai_engine)
            context = f"Capture d'écran issue de {os.path.basename(video_path)}"
            suggestion = service.suggest_thumbnail(context)
            return _first_six_words(suggestion or "")
        except Exception:
            # Une IA défaillante ne doit jamais faire échouer la génération
            # de miniatures, ni produire un texte inventé
            return ""

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        try:
            if not video_path or not os.path.exists(video_path):
                return PostProcessResult(
                    name=self.name, success=False,
                    error="Fichier vidéo introuvable")

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                cap.release()
                return PostProcessResult(
                    name=self.name, success=False,
                    error="Impossible d'ouvrir la vidéo")

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            positions = _sample_positions(frame_count, samples=40)

            scored: List[Tuple[int, bool, float, np.ndarray]] = []
            for idx, pos in enumerate(positions):
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                has_content, sharpness = _score_frame(frame)
                scored.append((pos, has_content, sharpness, frame))
                if positions:
                    progress_cb(0.1 + 0.6 * (idx + 1) / len(positions))

            cap.release()

            if not scored:
                return PostProcessResult(
                    name=self.name, success=False,
                    error="Aucune frame lisible dans la vidéo")

            # Préférence : frames avec du contenu (pas noires/uniformes),
            # triées par netteté décroissante ; à défaut, on retombe sur
            # toutes les frames disponibles pour ne jamais échouer.
            with_content = [s for s in scored if s[1]]
            pool = with_content if with_content else scored
            pool_sorted = sorted(pool, key=lambda s: s[2], reverse=True)

            # Garde les meilleures candidates puis les répartit dans le
            # temps pour éviter 3 miniatures quasi identiques.
            top_n = max(self.count * 3, self.count)
            best_candidates = pool_sorted[:top_n]
            best_positions = [c[0] for c in best_candidates]
            chosen_positions = _pick_spread_indices(best_positions, self.count)

            by_pos = {s[0]: s[3] for s in scored}
            chosen_frames = [by_pos[p] for p in chosen_positions
                            if p in by_pos]
            # Vidéo trop courte pour `count` frames distinctes : on en
            # produit moins plutôt que de livrer des copies identiques
            # présentées comme des propositions différentes
            if not chosen_frames:
                return PostProcessResult(
                    name=self.name, success=False,
                    error="Aucune frame exploitable pour les miniatures")

            caption = self._suggest_caption(video_path)
            progress_cb(0.8)

            stem = Path(video_path).with_suffix('')
            output_paths = []
            for i, frame in enumerate(chosen_frames[:self.count], start=1):
                out_frame = _draw_caption(frame, caption) if caption else frame
                out_path = f"{stem}_thumb{i}.png"
                ok = cv2.imwrite(out_path, out_frame)
                if not ok:
                    return PostProcessResult(
                        name=self.name, success=False,
                        error=f"Échec de l'écriture de {out_path}")
                output_paths.append(out_path)

            progress_cb(1.0)
            return PostProcessResult(
                name=self.name, success=True,
                output_path=output_paths[0],
                error=(None if len(output_paths) == self.count
                      else f"{len(output_paths)} miniature(s) générée(s)"))
        except Exception as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=str(e))
