"""La page et son script partagent des identifiants : ce test empêche
qu'un renommage d'un côté laisse l'autre appeler un noeud absent. Il
vérifie aussi ce qui ne doit plus exister (fond animé, propriété
Electron ignorée par WebView2)."""

import re
from pathlib import Path

from webui.app import (purger_profil_webview_si_nouvelle_version,
                       webview_storage_path)

ASSETS = Path(__file__).parent.parent / 'src' / 'webui' / 'assets'

IDS_ATTENDUS = [
    # capsule
    'timer', 'status', 'hotkey', 'record', 'open-folder', 'smart-focus-btn',
    'pill-mic', 'pill-system', 'pill-webcam', 'open-extensions',
    'open-settings', 'minimize', 'close', 'update-pill',
    'onde-repos', 'progress', 'progress-step', 'progress-bar',
    # décompte
    'countdown', 'countdown-value', 'countdown-webcam', 'countdown-format',
    # widget
    'widget-label', 'widget-timer', 'widget-hours', 'widget-format',
    'widget-res', 'widget-size', 'widget-cam', 'widget-cam-img',
    'widget-pause', 'widget-stop', 'widget-wave',
    # feuilles
    'sheet-settings', 'sheet-extensions', 'sheet-ai', 'sheet-update',
    'tab-capture', 'tab-audio', 'tab-webcam', 'tab-ia', 'version-tag',
    # réglages
    'resolution', 'bitrate', 'folder', 'smart-focus', 'mic', 'device',
    'cursor-visible', 'click-halo', 'cursor-hint',
    'system-audio', 'gain', 'gain-value',
    'webcam-enabled', 'webcam-device', 'webcam-forme', 'webcam-coin',
    'webcam-taille', 'webcam-miroir', 'webcam-test', 'webcam-preview',
    'webcam-hint', 'webcam-erreur', 'onglets-trait',
    'provider-line', 'open-ai-config', 'charge-warning',
    'privacy_blur', 'clean_canvas', 'overlay', 'subtitles', 'magic_cut',
    'magic_cut_max', 'delete_original', 'subtitle_fix', 'summary',
    'thumbnails',
    # extensions, IA, mise à jour
    'extension-list', 'plugin-list', 'plugins-folder', 'plugins-status',
    'ai-provider', 'ai-model', 'ai-model-hint', 'ai-key-field', 'ai-key',
    'ai-privacy', 'ai-status', 'ai-test', 'ai-save',
    'update-version', 'update-notes', 'update-progress',
    'update-progress-bar', 'update-progress-label', 'update-status',
    'update-later', 'update-install', 'update-size',
]


def test_tous_les_identifiants_sont_dans_la_page():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    manquants = [i for i in IDS_ATTENDUS if i not in ids]
    assert manquants == []


def test_les_identifiants_appeles_par_le_script_existent():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    js = (ASSETS / 'app.js').read_text(encoding='utf-8')
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    appeles = set(re.findall(r"\$\('([^']+)'\)", js))
    assert appeles - ids == set()


def test_pas_de_fond_anime_ni_de_propriete_electron():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    css = (ASSETS / 'style.css').read_text(encoding='utf-8')
    js = (ASSETS / 'app.js').read_text(encoding='utf-8')
    assert 'shards' not in html and 'shards' not in js
    assert not (ASSETS / 'shards.js').exists()
    assert '-webkit-app-region' not in css and '-webkit-app-region' not in html


def test_les_zones_de_saisie_existent():
    """Sans cadre Windows, seule cette classe permet de déplacer la
    fenêtre — pywebview l'écoute."""
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    assert html.count('pywebview-drag-region') >= 3


def test_le_profil_webview_est_fixe():
    """Le profil jetable (private_mode=True) faisait échouer sa propre
    suppression à la sortie : Crashpad tient encore
    CrashpadMetrics-active.pma, d'où « [WinError 5] ». On utilise un
    profil fixe, purgé au changement de version."""
    source = (Path(__file__).parent.parent / 'src' / 'webui' / 'app.py'
              ).read_text(encoding='utf-8')
    assert 'private_mode=True' not in source
    assert 'private_mode=False' in source
    assert 'storage_path=' in source


# --- purge du profil WebView2 au changement de version ------------------

def test_le_profil_est_purge_quand_la_version_change(tmp_path):
    """Motif du profil jetable à l'origine : après une mise à jour,
    WebView2 servait l'index.html mis en cache."""
    (tmp_path / 'version.txt').write_text('1.4.0', encoding='utf-8')
    cache = tmp_path / 'EBWebView'
    cache.mkdir()
    (cache / 'index-perime.html').write_text('vieux', encoding='utf-8')

    assert purger_profil_webview_si_nouvelle_version(tmp_path, '1.5.0') is True
    assert not cache.exists()
    assert (tmp_path / 'version.txt').read_text(encoding='utf-8') == '1.5.0'


def test_le_profil_est_conserve_a_version_egale(tmp_path):
    """Un lancement ordinaire ne doit rien purger : le profil sert au
    cache et évite de tout recharger à chaque démarrage."""
    (tmp_path / 'version.txt').write_text('1.5.0', encoding='utf-8')
    cache = tmp_path / 'EBWebView'
    cache.mkdir()
    (cache / 'utile.dat').write_text('garder', encoding='utf-8')

    assert purger_profil_webview_si_nouvelle_version(tmp_path, '1.5.0') is False
    assert (cache / 'utile.dat').exists()


def test_profil_sans_marqueur_est_purge(tmp_path):
    """Premier lancement après la bascule depuis le profil jetable."""
    cache = tmp_path / 'EBWebView'
    cache.mkdir()
    (cache / 'vieux.dat').write_text('x', encoding='utf-8')

    assert purger_profil_webview_si_nouvelle_version(tmp_path, '1.5.0') is True
    assert (tmp_path / 'version.txt').read_text(encoding='utf-8') == '1.5.0'


def test_dossier_absent_est_cree_sans_lever(tmp_path):
    cible = tmp_path / 'pas-encore' / 'webview'

    purger_profil_webview_si_nouvelle_version(cible, '1.5.0')

    assert cible.is_dir()
    assert (cible / 'version.txt').exists()


def test_un_fichier_verrouille_ne_fait_pas_lever(tmp_path, monkeypatch):
    """Cas réel : Crashpad tient un fichier ouvert. La purge doit se
    poursuivre et le démarrage ne jamais être bloqué."""
    (tmp_path / 'version.txt').write_text('1.4.0', encoding='utf-8')
    (tmp_path / 'verrouille.pma').write_text('x', encoding='utf-8')
    (tmp_path / 'libre.dat').write_text('x', encoding='utf-8')

    vrai_unlink = Path.unlink

    def unlink_recalcitrant(self, *a, **kw):
        if self.name == 'verrouille.pma':
            raise PermissionError(5, "Accès refusé")
        return vrai_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, 'unlink', unlink_recalcitrant)

    # Ne lève pas, et purge quand même ce qui est libérable
    purger_profil_webview_si_nouvelle_version(tmp_path, '1.5.0')

    assert not (tmp_path / 'libre.dat').exists()
    assert (tmp_path / 'verrouille.pma').exists()


def test_marqueur_illisible_est_traite_comme_perime(tmp_path, monkeypatch):
    """Un version.txt qu'on ne peut pas lire ne doit pas empêcher la
    purge : le choix sûr est de considérer le profil périmé."""
    (tmp_path / 'version.txt').write_text('1.5.0', encoding='utf-8')
    (tmp_path / 'cache.dat').write_text('x', encoding='utf-8')

    vrai_read = Path.read_text

    def read_recalcitrant(self, *a, **kw):
        if self.name == 'version.txt':
            raise PermissionError(5, "Accès refusé")
        return vrai_read(self, *a, **kw)

    monkeypatch.setattr(Path, 'read_text', read_recalcitrant)

    assert purger_profil_webview_si_nouvelle_version(tmp_path, '1.5.0') is True
    assert not (tmp_path / 'cache.dat').exists()


def test_le_profil_vit_dans_localappdata(monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', r'C:\Users\test\AppData\Local')

    chemin = webview_storage_path()

    assert chemin.name == 'webview'
    assert chemin.parent.name == 'LuminaRecorder'


def test_aucune_ressource_distante():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    css = (ASSETS / 'style.css').read_text(encoding='utf-8')
    assert 'http://' not in html and 'https://' not in html
    assert '@import' not in css and 'url(http' not in css
