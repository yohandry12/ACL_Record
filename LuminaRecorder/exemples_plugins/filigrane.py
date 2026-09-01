"""Exemple de plugin Lumina : incruste un texte dans un coin.

Copiez ce fichier dans le dossier des plugins, puis activez-le depuis
le panneau Extensions.

C'est le plus simple des deux contrats : un filtre temps réel, appelé
pour chaque image capturée.
"""

import cv2

from filters.base import FrameFilter

# Ce bloc est lu SANS exécuter le fichier : Lumina peut donc afficher
# votre plugin dans la liste sans lui faire confiance. Gardez-le en
# haut du fichier, littéral, sans variable ni appel de fonction.
LUMINA_PLUGIN = {
    'nom': 'Filigrane',
    'description': 'Incruste un texte dans le coin de la vidéo',
    'auteur': 'Lumina',
    'version': '1.0',
    # Version du contrat pour laquelle ce plugin est écrit. Un plugin
    # déclarant un numéro supérieur à celui de Lumina est refusé avec
    # un message clair, plutôt que de planter en pleine capture.
    'api': 1,
}

TEXTE = "Lumina"


class Plugin(FrameFilter):
    """Un filtre reçoit chaque image et retourne l'image transformée.

    Contrainte : garder les mêmes dimensions et le même type. Un filtre
    trop lent est désactivé automatiquement pendant l'enregistrement —
    la capture n'est jamais interrompue.
    """

    name = "Filigrane"

    def process(self, frame):
        hauteur, largeur = frame.shape[:2]

        # Taille proportionnelle à la largeur. Mesuré : à taille fixe,
        # le filigrane couvre le même nombre de pixels en 1366x768
        # qu'en 3840x2160 — soit un timbre-poste illisible en 4K. Ici
        # la couverture suit la résolution (x4,3 entre les deux).
        echelle = max(0.4, min(1.2, largeur / 1920 * 1.0))
        epaisseur = max(1, int(echelle * 2))
        (largeur_texte, hauteur_texte), _ = cv2.getTextSize(
            TEXTE, cv2.FONT_HERSHEY_SIMPLEX, echelle, epaisseur)
        marge = max(6, int(largeur * 0.01))
        x = max(marge, largeur - largeur_texte - marge)
        y = max(hauteur_texte + marge, hauteur - marge)

        cv2.putText(frame, TEXTE, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    echelle, (255, 255, 255), epaisseur, cv2.LINE_AA)
        return frame
