"""La page et son script partagent des identifiants : ce test empêche
qu'un renommage d'un côté laisse l'autre appeler un noeud absent. Il
vérifie aussi ce qui ne doit plus exister (fond animé, propriété
Electron ignorée par WebView2)."""

import re
from pathlib import Path

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
    'system-audio', 'gain', 'gain-value',
    'webcam-enabled', 'webcam-device', 'webcam-forme', 'webcam-coin',
    'webcam-taille', 'webcam-miroir', 'webcam-test', 'webcam-preview',
    'webcam-hint',
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


def test_aucune_ressource_distante():
    html = (ASSETS / 'index.html').read_text(encoding='utf-8')
    css = (ASSETS / 'style.css').read_text(encoding='utf-8')
    assert 'http://' not in html and 'https://' not in html
    assert '@import' not in css and 'url(http' not in css
