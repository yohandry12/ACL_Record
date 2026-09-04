"""Preuve sur machine : la webcam s'incruste et coûte ce qu'annoncé.

Usage : python tools/verifier_webcam.py
Ouvre la caméra 0, compose 150 images 1366×768 avec le filtre en
« moyenne », écrit tools/verif_webcam.jpg et affiche le coût moyen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import cv2
import numpy as np

from core.webcam_source import WebcamSource, lister_webcams
from filters.webcam_overlay_filter import WebcamOverlayFilter


def main():
    cams = lister_webcams()
    print("Caméras :", cams or "aucune")
    if not cams:
        return 1
    source = WebcamSource(device_index=cams[0]['index'])
    t0 = time.perf_counter()
    source.start()
    while not source.prete and not source.erreur and time.perf_counter() - t0 < 8:
        time.sleep(0.05)
    print(f"Ouverture : {time.perf_counter() - t0:.2f} s, erreur : {source.erreur!r}")
    if not source.prete:
        source.stop()
        return 1

    flt = WebcamOverlayFilter(source, forme='rond', coin='bas-droite',
                              taille='moyenne')
    frame = np.full((768, 1366, 3), 40, np.uint8)
    for _ in range(20):
        flt.process(frame.copy())
    t0 = time.perf_counter()
    n = 150
    for _ in range(n):
        sortie = flt.process(frame.copy())
    print(f"Coût moyen : {(time.perf_counter() - t0) / n * 1000:.2f} ms")
    chemin = Path(__file__).parent / 'verif_webcam.jpg'
    cv2.imwrite(str(chemin), sortie)
    print("Image :", chemin)
    source.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
