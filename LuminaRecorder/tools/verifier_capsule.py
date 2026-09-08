"""Preuve sur machine de l'interface « capsule ».

Usage : python tools/verifier_capsule.py

Le script lance la vraie application (`webui.app.run`, pont réel), pilote
la page par `evaluate_js` depuis un thread de travail, et vérifie quatre
points :

1. capsule au repos : fenêtre 440×352, coins arrondis ;
2. feuille de réglages, puis onglet Webcam ;
3. enregistrement : fenêtre 360×180 en haut à droite, et la fenêtre est
   bien absente d'une capture d'écran complète (`mss`) ;
4. retour au repos : 440×352 à la position d'origine.

Il imprime un tableau OK/ÉCHEC et sort en 1 au premier échec. Les quatre
images sont écrites dans `tools/capsule_*.png`.

Pourquoi tout se passe DANS le processus de l'application, et pourquoi
la capture n'utilise pas `PrintWindow` :

* `PrintWindow` (même avec `PW_RENDERFULLCONTENT`) rend une image
  entièrement noire : WebView2 compose en Direct3D dans une fenêtre
  fille (« Intermediate D3D Window »), son contenu n'est pas dans le DC
  de la fenêtre. Mesuré pendant la tâche 3.
* Une capture d'écran externe ne voit pas non plus la fenêtre pendant
  `pending`/`recording` : le pont pose `WDA_EXCLUDEFROMCAPTURE` — c'est
  précisément ce qui rend le widget absent de la vidéo. Et
  `SetWindowDisplayAffinity` **depuis un autre processus est refusé par
  Windows** (GetLastError = 5).

Donc : on lève l'exclusion le temps du cliché (possible seulement depuis
le processus propriétaire), on photographie par `ImageGrab`, puis on la
remet aussitôt. La vérification d'exclusion du point 3, elle, se fait
**sans rien lever**, avec `mss`, exactement comme un logiciel de capture
tiers verrait l'écran.
"""
import ctypes
import sys
import threading
import time
from ctypes import windll
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = Path(__file__).resolve().parent
# `src` d'abord (webui, core…), la racine ensuite (version, main)
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / 'src'))

TITRE = 'Lumina Recorder'
CAPSULE = (440, 352)
WIDGET = (360, 180)

# Couleur de la bande du widget : oklch(76.9% 0.166 70.1) ≈ #F59E0B.
# mss rend du BGRA : (11, 158, 245).
AMBRE_RGB = (245, 158, 11)
TOLERANCE = 40          # écart par canal accepté
SEUIL_PIXELS = 200      # au-delà, on considère la bande présente
# Marque positive de la capsule dans un cliché : bouton REC au repos,
# soulignement d'onglet des feuilles, bande du widget. En deçà, c'est la
# fenêtre d'en dessous qui a été photographiée.
SEUIL_CAPSULE = 50

resultats = []          # (libellé, ok, détail)


def note(libelle, ok, detail=''):
    resultats.append((libelle, bool(ok), detail))
    marque = 'OK   ' if ok else 'ÉCHEC'
    print(f"  [{marque}] {libelle}" + (f" — {detail}" if detail else ''),
          flush=True)


def tableau_et_sortie():
    """Imprime le tableau final et rend le code de sortie."""
    print()
    print("┌───────┬──────────────────────────────────────────────────────┐")
    print("│ État  │ Point de contrôle                                    │")
    print("├───────┼──────────────────────────────────────────────────────┤")
    for libelle, ok, _ in resultats:
        marque = 'OK   ' if ok else 'ÉCHEC'
        print(f"│ {marque} │ {libelle[:52]:<52s} │")
    print("└───────┴──────────────────────────────────────────────────────┘")
    echecs = [libelle for libelle, ok, _ in resultats if not ok]
    if echecs:
        print(f"\n{len(echecs)} point(s) en échec : {', '.join(echecs)}")
        return 1
    print(f"\n{len(resultats)} points vérifiés, tous conformes.")
    return 0


class Echec(Exception):
    """Premier échec : on arrête le scénario et on sort en 1."""


def pilote(fin):
    """Scénario de vérification. Tourne dans un thread, hors de la
    boucle d'événements de la fenêtre."""
    import win32con
    import win32gui
    import webview
    import mss
    import numpy as np
    from PIL import ImageGrab

    def fenetre():
        return webview.windows[0] if webview.windows else None

    def js(code):
        w = fenetre()
        if not w:
            return None
        try:
            return w.evaluate_js(code)
        except Exception as e:
            print(f"  [js] erreur : {e!r}", flush=True)
            return None

    def pont():
        """Le pont réel, atteint sans passer par la page.

        `window.pywebview.api.toggle_recording()` depuis `evaluate_js`
        traverse la page puis revient au pont : deux allers-retours par
        le thread d'interface. Or `emit` (minuterie, encodage) appelle
        lui aussi `evaluate_js`, une fois par seconde pendant toute la
        capture, sous `_emit_lock`. L'appel du scénario se retrouvait
        indéfiniment derrière ces émissions et le point 4 ne finissait
        jamais. On appelle donc la méthode Python directement : c'est
        exactement ce que le raccourci F9 fait de son côté.
        """
        w = fenetre()
        return getattr(w, '_js_api', None) if w else None

    def hwnd():
        return win32gui.FindWindow(None, TITRE)

    def rect():
        h = hwnd()
        return win32gui.GetWindowRect(h) if h else None

    def taille():
        r = rect()
        if not r:
            return None
        return (r[2] - r[0], r[3] - r[1])

    def capture(nom, etiquette=''):
        """Cliché de la fenêtre, exclusion de capture levée le temps du
        cliché puis rendue telle qu'elle était."""
        h = hwnd()
        if not h:
            print(f"  [cap] {nom} : fenêtre introuvable", flush=True)
            return None
        avant = ctypes.c_uint(0)
        windll.user32.GetWindowDisplayAffinity(h, ctypes.byref(avant))
        windll.user32.SetWindowDisplayAffinity(h, 0)   # WDA_NONE
        try:
            win32gui.SetWindowPos(
                h, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                | win32con.SWP_NOACTIVATE)
            # Passer TOPMOST ne suffit pas : tant que la fenêtre n'est pas
            # active, WebView2 peut ne pas avoir recomposé. On la met au
            # premier plan — autorisé depuis le processus propriétaire,
            # refusé depuis un autre ; l'échec n'est pas bloquant.
            try:
                win32gui.SetForegroundWindow(h)
            except Exception:
                pass
            # Le premier cliché peut encore montrer la fenêtre d'en
            # dessous (constaté : VS Code à la place de la capsule). Un
            # critère de « fond sombre » se laisse tromper par le thème
            # sombre de VS Code : on cherche donc une marque POSITIVE de
            # la capsule, l'ambre (#F59E0B) — bouton REC au repos,
            # soulignement d'onglet des feuilles, bande du widget.
            img = None
            for _ in range(8):
                time.sleep(0.4)
                img = ImageGrab.grab(bbox=win32gui.GetWindowRect(h),
                                     all_screens=True)
                pixels = np.asarray(img.convert('RGB')).astype(np.int16)
                cible = np.array(AMBRE_RGB, dtype=np.int16)
                ambres = int((np.abs(pixels - cible)
                              <= TOLERANCE).all(axis=2).sum())
                if ambres >= SEUIL_CAPSULE:
                    break
            chemin = SORTIE / f"{nom}.png"
            img.save(chemin)
            print(f"  [cap] {chemin.name} {img.size} {etiquette} "
                  f"({ambres} px ambres)", flush=True)
            return chemin
        finally:
            windll.user32.SetWindowDisplayAffinity(h, avant.value)

    def attendre_etat(attendu, limite=25.0, tracer=False):
        """Attend que la page affiche `attendu`.

        `tracer` imprime l'état lu chaque seconde : indispensable pour
        distinguer une page bloquée d'un encodage simplement long.
        """
        t0 = time.perf_counter()
        dernier_trace = 0.0
        while time.perf_counter() - t0 < limite:
            etat = js("document.body.dataset.state")
            if etat == attendu:
                return True
            ecoule = time.perf_counter() - t0
            if tracer and ecoule - dernier_trace >= 1.0:
                dernier_trace = ecoule
                print(f"    [{ecoule:5.1f} s] état = {etat!r}", flush=True)
            time.sleep(0.25)
        return False

    def pixels_ambres(zone):
        """Nombre de pixels ambres dans une capture d'écran complète,
        restreinte au rectangle `zone` (gauche, haut, droite, bas).

        Aucune levée d'exclusion ici : on regarde l'écran exactement
        comme le ferait un logiciel de capture tiers.
        """
        gauche, haut, droite, bas = zone
        # mss.MSS remplace mss.mss (déprécié) dans les versions récentes
        with getattr(mss, 'MSS', mss.mss)() as sct:
            plein = sct.grab(sct.monitors[0])
            origine_x, origine_y = sct.monitors[0]['left'], sct.monitors[0]['top']
            brut = np.frombuffer(plein.rgb, dtype=np.uint8)
            image = brut.reshape(plein.height, plein.width, 3)
        x0 = max(0, gauche - origine_x)
        y0 = max(0, haut - origine_y)
        x1 = min(image.shape[1], droite - origine_x)
        y1 = min(image.shape[0], bas - origine_y)
        if x1 <= x0 or y1 <= y0:
            return -1, (0, 0)
        region = image[y0:y1, x0:x1].astype(np.int16)
        cible = np.array(AMBRE_RGB, dtype=np.int16)
        proche = (np.abs(region - cible) <= TOLERANCE).all(axis=2)
        return int(proche.sum()), (x1 - x0, y1 - y0)

    try:
        # ------------------------------------------------------------------
        # Point 1 — capsule au repos
        # ------------------------------------------------------------------
        print("\n1. Capsule au repos", flush=True)
        # La page se remplit lentement (énumération micros/caméras,
        # sondage du fournisseur IA) : on attend l'état, pas un délai fixe.
        if not attendre_etat('idle', 40):
            note("Page prête à l'état « idle »", False,
                 f"état lu : {js('document.body.dataset.state')!r}")
            raise Echec
        note("Page prête à l'état « idle »", True)

        # `applyState` pose l'état AVANT que `populateSettings` n'ait fini :
        # `get_initial_state` prend plusieurs secondes sur cette machine
        # (énumération des micros et des caméras, sondage du fournisseur
        # IA). Sans cette seconde attente, les captures des réglages
        # montrent des listes vides, « Dossier de sortie — » et « v— ».
        # On attend donc le dernier champ rempli, la version en pied.
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 40:
            v = js("document.getElementById('version-tag').textContent")
            if v and v not in ('v—', 'v-'):
                break
            time.sleep(0.3)
        note("Réglages remplis par le pont",
             bool(v) and v not in ('v—', 'v-'), f"version en pied : {v!r}")
        if not v or v in ('v—', 'v-'):
            raise Echec

        pos_origine = rect()
        t = taille()
        note("Fenêtre au repos : 440×352", t == CAPSULE, f"mesuré {t}")
        if t != CAPSULE:
            raise Echec

        # Coins arrondis : sur Windows 10 la fenêtre est découpée par une
        # région (GetWindowRgn ≠ 0). Sur Windows 11 c'est DWM qui arrondit,
        # sans région : le point n'est alors pas applicable.
        h = hwnd()
        region = windll.gdi32.CreateRectRgn(0, 0, 1, 1)
        rgn = windll.user32.GetWindowRgn(h, region)
        windll.gdi32.DeleteObject(region)
        build = sys.getwindowsversion().build
        if build >= 22000:
            note("Coins arrondis (Windows 11 : DWM)", True,
                 f"build {build}, région non requise")
        else:
            note("Coins arrondis (Windows 10 : GetWindowRgn ≠ 0)", rgn != 0,
                 f"build {build}, GetWindowRgn = {rgn}")
            if rgn == 0:
                raise Echec

        capture('capsule_repos', 'capsule au repos')

        # ------------------------------------------------------------------
        # Point 2 — feuille de réglages et onglet Webcam
        # ------------------------------------------------------------------
        print("\n2. Feuille de réglages", flush=True)
        js("document.getElementById('open-settings').click()")
        time.sleep(1.0)
        ouverte = js("document.getElementById('sheet-settings')"
                     ".classList.contains('ouverte')")
        note("La feuille de réglages s'ouvre", bool(ouverte),
             f"classe « ouverte » : {ouverte}")
        if not ouverte:
            raise Echec
        capture('capsule_reglages', 'feuille de réglages')

        js("document.querySelector('#onglets button[data-tab=\\'webcam\\']')"
           ".click()")
        time.sleep(0.9)
        actif = js("document.querySelector('#onglets button.actif')"
                   ".dataset.tab")
        note("L'onglet Webcam devient actif", actif == 'webcam',
             f"onglet actif : {actif!r}")
        if actif != 'webcam':
            raise Echec
        capture('capsule_webcam', 'réglages, onglet Webcam')

        # Rien ne doit sortir de la capsule ni déborder horizontalement
        debord = js("""
          (() => {
            const cap = document.getElementById('capsule').getBoundingClientRect();
            const corps = document.querySelector('.feuille.ouverte .feuille-corps');
            const dehors = [];
            document.querySelectorAll('.feuille.ouverte .feuille-corps *')
              .forEach((n) => {
                const r = n.getBoundingClientRect();
                if (!r.width && !r.height) return;
                if (r.right > cap.right + 0.6 || r.left < cap.left - 0.6) {
                  dehors.push(n.id || n.className || n.tagName);
                }
              });
            return JSON.stringify({
              dehors: dehors.slice(0, 6),
              horizontal: corps ? corps.scrollWidth > corps.clientWidth : null,
            });
          })()
        """)
        note("Aucun débordement horizontal dans l'onglet Webcam",
             debord and '"horizontal":false' in debord
             and '"dehors":[]' in debord, str(debord))

        js("document.dispatchEvent(new KeyboardEvent('keydown', "
           "{key: 'Escape'}))")
        time.sleep(0.9)
        pile = js("JSON.stringify(Array.from("
                  "document.querySelectorAll('.feuille.ouverte')).map(f=>f.id))")
        note("Échap referme la feuille", pile == '[]', f"pile : {pile}")
        if pile != '[]':
            raise Echec

        # ------------------------------------------------------------------
        # Point 3 — widget d'enregistrement et exclusion de capture
        # ------------------------------------------------------------------
        print("\n3. Enregistrement : widget et exclusion de capture",
              flush=True)
        api = pont()
        if api is None:
            note("Pont accessible depuis le scénario", False,
                 "window._js_api introuvable")
            raise Echec
        api.toggle_recording()
        if not attendre_etat('pending', 15):
            note("Passage en décompte", False,
                 f"état : {js('document.body.dataset.state')!r}")
            raise Echec
        note("Passage en décompte", True)

        if not attendre_etat('recording', 20):
            note("Passage en enregistrement", False,
                 f"état : {js('document.body.dataset.state')!r}")
            raise Echec
        note("Passage en enregistrement", True)
        # Laisser le widget se poser et le chrono avancer
        time.sleep(3.0)

        t = taille()
        note("Fenêtre du widget : 360×180", t == WIDGET, f"mesuré {t}")
        if t != WIDGET:
            raise Echec

        r_widget = rect()
        largeur_ecran = windll.user32.GetSystemMetrics(0)
        en_haut_a_droite = (r_widget[1] < 200
                            and r_widget[2] > largeur_ecran - 200)
        note("Widget posé en haut à droite", en_haut_a_droite,
             f"rect {r_widget}, écran {largeur_ecran} px de large")

        # Exclusion de capture : capture d'écran complète par mss, SANS
        # lever WDA_EXCLUDEFROMCAPTURE. La bande ambre du widget ne doit
        # pas s'y trouver.
        affinite = ctypes.c_uint(0)
        windll.user32.GetWindowDisplayAffinity(hwnd(), ctypes.byref(affinite))
        n_ambre, dims = pixels_ambres(r_widget)
        note("Affinité WDA_EXCLUDEFROMCAPTURE posée", affinite.value == 0x11,
             f"GetWindowDisplayAffinity = {affinite.value} "
             f"(0x11 attendu)")
        note("Bande ambre absente de la capture d'écran (mss)",
             0 <= n_ambre < SEUIL_PIXELS,
             f"{n_ambre} pixel(s) ambres dans {dims[0]}×{dims[1]} "
             f"(seuil {SEUIL_PIXELS}, tolérance ±{TOLERANCE}/canal)")
        if not (0 <= n_ambre < SEUIL_PIXELS):
            raise Echec

        capture('capsule_widget', 'widget en enregistrement')

        # ------------------------------------------------------------------
        # Point 4 — retour au repos
        # ------------------------------------------------------------------
        print("\n4. Retour au repos", flush=True)
        api.toggle_recording()
        # L'encodage FFmpeg puis le post-traitement tiennent l'état
        # « processing » : sur cette machine, une dizaine de secondes pour
        # quelques secondes de capture. La trace montre la progression.
        if not attendre_etat('idle', 180, tracer=True):
            note("Retour à l'état « idle »", False,
                 f"état : {js('document.body.dataset.state')!r}")
            raise Echec
        note("Retour à l'état « idle »", True)
        time.sleep(1.5)

        t = taille()
        note("Fenêtre rendue à 440×352", t == CAPSULE, f"mesuré {t}")

        r_final = rect()
        ecart = (abs(r_final[0] - pos_origine[0]),
                 abs(r_final[1] - pos_origine[1]))
        note("Fenêtre rendue à sa position d'origine",
             max(ecart) <= 4,
             f"origine {pos_origine[:2]} → final {r_final[:2]}")

        affinite = ctypes.c_uint(0)
        windll.user32.GetWindowDisplayAffinity(hwnd(), ctypes.byref(affinite))
        note("Exclusion de capture levée au repos", affinite.value == 0,
             f"GetWindowDisplayAffinity = {affinite.value}")

    except Echec:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        note(f"Exception : {type(e).__name__}", False, str(e))
    finally:
        fin['code'] = tableau_et_sortie()
        # Fermer la fenêtre rend la main à webview.start() dans le thread
        # principal, qui sort alors avec ce code
        try:
            w = fenetre()
            if w:
                w.destroy()
        except Exception:
            pass


def main():
    fin = {'code': 1}
    # Même préparation que main.py : sans conscience du DPI, les
    # coordonnées de fenêtre et les pixels capturés ne sont pas dans le
    # même repère sur un écran mis à l'échelle.
    from core.window_detect import enable_dpi_awareness
    from plugins.loader import enregistrer_chemins_externes
    enregistrer_chemins_externes()
    enable_dpi_awareness()

    threading.Thread(target=pilote, args=(fin,), daemon=True,
                     name='verifier-capsule').start()

    from webui.app import run
    run()
    return fin['code']


if __name__ == '__main__':
    sys.exit(main())
