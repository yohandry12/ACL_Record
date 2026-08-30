"""
Lumina PostProcess - Traitements appliqués après l'arrêt de l'enregistrement.

Règle d'or : le runner n'échoue jamais. Un processeur qui lève une
exception produit un PostProcessResult(success=False) et on passe au
suivant — le fichier original n'est jamais perdu ni modifié.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class PostProcessResult:
    name: str
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None


class PostProcessor(ABC):
    """Traitement post-enregistrement produisant un fichier séparé."""

    name: str = "postprocessor"

    @abstractmethod
    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        ...


def run_postprocessors(processors: List[PostProcessor], video_path: str,
                       audio_path: Optional[str],
                       progress_cb: Callable[[float], None],
                       step_cb: Optional[Callable[[str], None]] = None
                       ) -> List[PostProcessResult]:
    results: List[PostProcessResult] = []
    total = len(processors)

    for i, proc in enumerate(processors):
        if step_cb:
            step_cb(proc.name)

        def scoped_progress(p, _i=i):
            progress_cb(min(1.0, (_i + max(0.0, min(1.0, p))) / total))

        try:
            result = proc.run(video_path, audio_path, scoped_progress)
        except Exception as e:
            result = PostProcessResult(name=proc.name, success=False,
                                       error=str(e))
        results.append(result)
        progress_cb(min(1.0, (i + 1) / total))

    return results
