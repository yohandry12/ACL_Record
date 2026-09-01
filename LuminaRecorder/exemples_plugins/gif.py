"""Exemple de plugin Lumina : convertit la fin de l'enregistrement en GIF.

Montre le second point d'extension : un post-traitement, exécuté après
l'arrêt de la capture, qui produit un fichier supplémentaire sans
jamais toucher à l'enregistrement d'origine.

Règle absolue de ce contrat : **ne jamais lever d'exception**. Un
post-traitement qui plante ferait perdre les résultats de ceux qui le
suivent. En cas d'échec, on retourne un résultat qui l'explique.
"""

import subprocess
from pathlib import Path

from postprocess.base import PostProcessor, PostProcessResult

LUMINA_PLUGIN = {
    'nom': 'Conversion GIF',
    'description': 'Convertit les 10 dernières secondes en GIF',
    'auteur': 'Lumina',
    'version': '1.0',
    'api': 1,
}

SECONDES = 10


class Plugin(PostProcessor):
    """Post-traitement : reçoit la vidéo finie, produit un fichier à côté."""

    name = "Conversion GIF"

    def run(self, video_path, audio_path, progress_cb):
        # Écrire à côté de la vidéo, jamais par-dessus : l'original de
        # l'utilisateur ne doit courir aucun risque.
        sortie = str(Path(video_path).with_suffix('.gif'))
        progress_cb(0.1)
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-sseof', f'-{SECONDES}', '-i', video_path,
                 '-vf', 'fps=12,scale=480:-1:flags=lanczos', '-loop', '0',
                 sortie],
                check=True, capture_output=True)
        except Exception as e:
            # On rend l'échec lisible plutôt que de le laisser remonter
            return PostProcessResult(name=self.name, success=False,
                                     error=str(e))
        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=sortie)
