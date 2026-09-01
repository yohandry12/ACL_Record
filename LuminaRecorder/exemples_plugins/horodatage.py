"""Exemple de plugin Lumina : incruste l'heure courante sur la vidéo.

Ce que cet exemple montre en plus du filigrane :

1. **Un état entre les images.** `__init__` s'exécute une fois, avant
   la capture ; `process` s'exécute des milliers de fois. Tout ce qui
   coûte cher va dans `__init__`.
2. **Le respect du budget temps réel.** Formater une date coûte peu,
   mais le faire 60 fois par seconde pour rien reste du gaspillage :
   on ne reformate qu'au changement de seconde.
3. **La lisibilité sur n'importe quel fond.** Un texte blanc sur un
   fond clair est invisible ; un contour sombre le rend lisible
   partout, sans connaître le contenu de l'écran.
"""

import time

import cv2

from filters.base import FrameFilter

LUMINA_PLUGIN = {
    'nom': 'Horodatage',
    'description': "Affiche l'heure courante en haut à gauche",
    'auteur': 'Lumina',
    'version': '1.0',
    'api': 1,
}

FORMAT = "%H:%M:%S"


class Plugin(FrameFilter):
    """Filtre temps réel avec un état conservé entre les images."""

    name = "Horodatage"

    def __init__(self):
        # Toujours appeler le constructeur parent : c'est lui qui pose
        # `self.enabled`, dont la chaîne de filtres se sert pour
        # désactiver un plugin défaillant.
        super().__init__()
        self._derniere_seconde = -1
        self._texte = ""

    def process(self, frame):
        maintenant = int(time.time())
        if maintenant != self._derniere_seconde:
            self._derniere_seconde = maintenant
            self._texte = time.strftime(FORMAT)

        hauteur, largeur = frame.shape[:2]
        echelle = max(0.4, min(1.2, largeur / 1920 * 1.0))
        epaisseur = max(1, int(echelle * 2))
        marge = max(6, int(largeur * 0.01))
        (_, hauteur_texte), _ = cv2.getTextSize(
            self._texte, cv2.FONT_HERSHEY_SIMPLEX, echelle, epaisseur)
        position = (marge, hauteur_texte + marge)

        # Contour sombre d'abord, texte clair par-dessus : lisible aussi
        # bien sur un fond blanc que sur un fond noir.
        cv2.putText(frame, self._texte, position, cv2.FONT_HERSHEY_SIMPLEX,
                    echelle, (0, 0, 0), epaisseur + 2, cv2.LINE_AA)
        cv2.putText(frame, self._texte, position, cv2.FONT_HERSHEY_SIMPLEX,
                    echelle, (255, 255, 255), epaisseur, cv2.LINE_AA)
        return frame
