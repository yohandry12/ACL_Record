/* Lumina Recorder — logique de l'interface
 *
 * Ne contient aucune règle métier : tout passe par window.pywebview.api,
 * et l'état affiché vient des événements poussés par le pont Python.
 * Dupliquer ici la logique de l'enregistrement garantirait qu'elle
 * diverge du moteur.
 */

import { ShardField } from './shards.js';

const $ = (id) => document.getElementById(id);

const el = {
  body: document.body,
  record: $('record'),
  recordLabel: $('record-label'),
  timer: $('timer'),
  widgetTimer: $('widget-timer'),
  widgetHours: $('widget-hours'),
  widgetSize: $('widget-size'),
  widgetLabel: $('widget-label'),
  widgetWave: $('widget-wave'),
  countdown: $('countdown'),
  countdownValue: $('countdown-value'),
  status: $('status'),
  profile: $('profile'),
  hotkey: $('hotkey'),
  hotkeyNote: $('hotkey-note'),
  progressBar: $('progress-bar'),
  progressStep: $('progress-step'),
  result: $('result'),
  resultPath: $('result-path'),
  device: $('device'),
  folder: $('folder'),
  gain: $('gain'),
  gainValue: $('gain-value'),
};

let state = 'idle';
let statusTimer = null;
let backdrop = null;

/* ---------- utilitaires ---------- */

function formatDuration(totalSeconds) {
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  const s = String(totalSeconds % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function formatSize(bytes) {
  if (!bytes) return '0 Mo';
  const mo = bytes / (1024 * 1024);
  if (mo >= 1024) return (mo / 1024).toFixed(2) + ' Go';
  return (mo >= 10 ? mo.toFixed(0) : mo.toFixed(1)) + ' Mo';
}

/* Le widget donne minutes:secondes ; les heures passent en exposant,
 * comme sur le modele, pour que les chiffres restent lisibles. */
function updateWidgetTime(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  const sec = String(totalSeconds % 60).padStart(2, '0');
  el.widgetTimer.textContent = `${m}:${sec}`;
  el.widgetHours.textContent = h > 0 ? `${h}h` : '';
}

function setStatus(message, kind) {
  el.status.textContent = message;
  el.status.className = 'status' + (kind ? ' ' + kind : '');
  // Les messages transitoires s'effacent ; les erreurs restent lisibles
  clearTimeout(statusTimer);
  if (kind !== 'error') {
    statusTimer = setTimeout(() => {
      if (state === 'idle') {
        el.status.textContent = 'Prêt à enregistrer';
        el.status.className = 'status';
      }
    }, 6000);
  }
}

async function call(method, ...args) {
  try {
    return await window.pywebview.api[method](...args);
  } catch (error) {
    setStatus('Erreur interne : ' + error, 'error');
    return { ok: false, error: String(error) };
  }
}

/* ---------- rendu de l'état ---------- */

function applyState(next) {
  state = next;
  el.body.dataset.state = next;
  // La barre compacte remplace la fenêtre pendant la capture : la fenêtre
  // pleine masquerait l'écran que l'on filme
  // Le widget apparait des le decompte : basculer au demarrage exact de
  // la capture ferait sauter la fenetre dans l'enregistrement lui-meme
  el.body.classList.toggle('compact',
    next === 'recording' || next === 'pending');

  const labels = {
    idle: "COMMENCER L'ENREGISTREMENT",
    pending: 'EN ATTENTE DE LA FENÊTRE…',
    recording: "ARRÊTER L'ENREGISTREMENT",
    processing: 'TRAITEMENT EN COURS…',
  };
  el.recordLabel.textContent = labels[next] || labels.idle;
  el.record.disabled = (next === 'processing');

  if (next === 'idle') {
    el.timer.textContent = '00:00:00';
    updateWidgetTime(0);
    el.widgetSize.textContent = '0 Mo';
    stopWave();
  }
  if (next === 'recording') startWave();

  // Le fond s'arrete des le decompte et jusqu'a la fin du traitement :
  // une animation permanente vole des cycles a la capture d'ecran, et
  // l'encodage FFmpeg qui suit sature deja le processeur.
  if (backdrop) {
    if (next === 'idle') backdrop.resume();
    else backdrop.pause();
  }
  if (next === 'pending') {
    el.widgetLabel.textContent = 'Préparation';
    setStatus('Démarrage dans quelques secondes…');
  } else {
    el.widgetLabel.textContent = 'Enregistrement';
  }
}

/* Point d'entrée des événements poussés par Python */
window.luminaEvent = function (message) {
  const { event, payload } = message;

  if (event === 'state') {
    applyState(payload);
  } else if (event === 'tick') {
    el.timer.textContent = formatDuration(payload.seconds);
    updateWidgetTime(payload.seconds);
    el.widgetSize.textContent = '≈ ' + formatSize(payload.bytes);
  } else if (event === 'countdown') {
    showCountdown(payload);
  } else if (event === 'progress') {
    if (payload.step) el.progressStep.textContent = payload.step;
    if (payload.value !== null && payload.value !== undefined) {
      el.progressBar.style.width = Math.round(payload.value * 100) + '%';
    }
  } else if (event === 'error') {
    setStatus(payload, 'error');
  } else if (event === 'notice') {
    setStatus(payload);
  } else if (event === 'done') {
    el.progressBar.style.width = '100%';
    showResult(payload);
  } else if (event === 'update_available') {
    onUpdateAvailable(payload);
  } else if (event === 'update_progress') {
    onUpdateProgress(payload);
  } else if (event === 'update_launching') {
    onUpdateLaunching();
  } else if (event === 'update_error') {
    onUpdateError(payload);
  }
};

/* ---------- Mise à jour automatique ----------
 *
 * Le pont pousse update_available quand une release plus récente est
 * publiée sur GitHub. La pastille de version passe en ambre ; le reste
 * ne bouge pas — une mise à jour ne doit jamais interrompre ce que
 * l'utilisateur est en train de faire.
 */

let updateInfo = null;
let updateDownloading = false;

function onUpdateAvailable(payload) {
  updateInfo = payload;
  const tag = $('version-tag');
  tag.textContent = payload.version + ' disponible';
  tag.classList.add('has-update');
  tag.title = 'Une mise à jour est prête — cliquer pour voir';
}

function openUpdateModal() {
  if (!updateInfo) return;
  $('update-version').textContent = updateInfo.version;
  $('update-size').textContent = updateInfo.size
    ? '(' + formatSize(updateInfo.size) + ')' : '';
  const notes = $('update-notes');
  notes.textContent = updateInfo.notes || '';
  notes.hidden = !updateInfo.notes;
  $('update-status').textContent = '';
  $('update-progress').hidden = true;
  $('update-install').disabled = false;
  $('update-later').disabled = false;
  // La boite grandit depuis la pastille de version qui l'a ouverte
  ancrerModale('update-modal', 'version-tag');
}

function closeUpdateModal() {
  // Pas de fermeture pendant le téléchargement : l'utilisateur doit
  // voir si son installateur est complet ou en échec
  if (updateDownloading) return;
  $('update-modal').hidden = true;
}

async function startUpdateInstall() {
  const result = await call('install_update');
  if (!result || !result.ok) {
    $('update-status').textContent =
      (result && result.error) || 'Mise à jour impossible';
    return;
  }
  updateDownloading = true;
  $('update-install').disabled = true;
  $('update-later').disabled = true;
  $('update-progress').hidden = false;
  $('update-status').textContent = 'Téléchargement…';
}

function onUpdateProgress(fraction) {
  const pct = Math.round((fraction || 0) * 100);
  $('update-progress-bar').style.width = pct + '%';
  $('update-progress-label').textContent = pct + ' %';
}

function onUpdateLaunching() {
  $('update-status').textContent =
    "L'installateur démarre — Lumina va se fermer.";
}

function onUpdateError(message) {
  updateDownloading = false;
  $('update-install').disabled = false;
  $('update-later').disabled = false;
  $('update-progress').hidden = true;
  $('update-status').textContent = message;
}


/* ---------- Extensions et plugins ----------
 *
 * La liste est construite en creant des noeuds, jamais par innerHTML
 * avec du texte de plugin : un nom de plugin est du contenu tiers, il
 * ne doit pas pouvoir injecter du balisage dans l'interface.
 */

async function openPluginsModal() {
  await renderPlugins();
  ancrerModale('plugins-modal', 'open-plugins');
}

function closePluginsModal() {
  $('plugins-modal').hidden = true;
}

async function renderPlugins() {
  const data = await call('get_plugins');
  const liste = $('plugin-list');
  liste.textContent = '';
  $('plugins-status').textContent = '';

  if (!data || !data.ok) {
    const vide = document.createElement('p');
    vide.className = 'plugin-vide';
    vide.textContent = (data && data.error)
      ? 'Dossier des plugins illisible : ' + data.error
      : 'Impossible de lire les plugins';
    liste.append(vide);
    return;
  }

  if (!data.plugins.length) {
    const vide = document.createElement('p');
    vide.className = 'plugin-vide';
    vide.textContent = 'Aucun plugin installé. Déposez un fichier .py '
      + 'dans le dossier des plugins.';
    liste.append(vide);
    return;
  }

  for (const p of data.plugins) {
    const ligne = document.createElement('div');
    ligne.className = 'plugin-item' + (p.erreur ? ' plugin-erreur' : '');

    const info = document.createElement('div');
    info.className = 'plugin-info';

    const titre = document.createElement('div');
    titre.className = 'plugin-nom';
    titre.textContent = p.nom;

    const detail = document.createElement('div');
    detail.className = 'plugin-detail';
    detail.textContent = p.erreur
      ? p.erreur
      : (p.description || 'Aucune description')
        + ' · ' + p.auteur + ' · v' + p.version;

    info.append(titre, detail);
    ligne.append(info);

    if (!p.erreur) {
      const inter = document.createElement('input');
      inter.type = 'checkbox';
      inter.checked = p.actif;
      inter.setAttribute('aria-label', 'Activer ' + p.nom);
      inter.addEventListener('change', async () => {
        await call('set_plugin_actif', p.identifiant, inter.checked);
        $('plugins-status').textContent =
          'Prend effet au prochain enregistrement';
      });
      ligne.append(inter);
    }

    liste.append(ligne);
  }
}

/* ---------- Forme d'onde du widget ----------
 *
 * IMPORTANT : ce trace ne mesure PAS le niveau du microphone. Le moteur
 * n'expose pas le niveau audio en temps reel, et afficher une amplitude
 * inventee ferait croire que le son est capte alors que le micro peut
 * etre coupe ou defaillant. C'est un rythme visuel qui signale « la
 * capture avance », rien d'autre.
 *
 * Le trace defile a gauche, comme une bande qui se deroule. Il s'arrete
 * completement hors enregistrement : aucune animation ne doit tourner
 * pendant que l'utilisateur ne regarde pas.
 */

let waveFrame = null;
let waveOffset = 0;

function drawWave() {
  const canvas = el.widgetWave;
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const middle = height / 2;
  const step = 7;
  const bars = Math.ceil(width / step) + 2;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.62)';

  for (let i = 0; i < bars; i += 1) {
    const x = i * step - (waveOffset % step);
    const seed = i + Math.floor(waveOffset / step);
    // Somme de sinusoides dephasees : irregulier a l'oeil, sans hasard,
    // donc stable d'une image a l'autre quand la bande defile
    const amplitude =
      Math.abs(Math.sin(seed * 0.7)) * 0.45 +
      Math.abs(Math.sin(seed * 0.31 + 1.2)) * 0.35 +
      Math.abs(Math.sin(seed * 1.9 + 0.4)) * 0.2;
    const barHeight = Math.max(2, amplitude * height * 0.78);
    ctx.fillRect(x, middle - barHeight / 2, 2.5, barHeight);
  }
}

function stepWave() {
  waveOffset += 0.55;
  drawWave();
  waveFrame = requestAnimationFrame(stepWave);
}

function startWave() {
  if (waveFrame !== null) return;
  // Respecter le reglage systeme : une animation permanente est un
  // probleme reel pour qui souffre de troubles vestibulaires
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    drawWave();
    return;
  }
  waveFrame = requestAnimationFrame(stepWave);
}

function stopWave() {
  if (waveFrame !== null) {
    cancelAnimationFrame(waveFrame);
    waveFrame = null;
  }
}

// La fenetre masquee continue de consommer si on ne l'arrete pas
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopWave();
  else if (state === 'recording') startWave();
});

/* Relance l'animation a chaque chiffre : sans cela le navigateur
 * reutilise l'animation en cours et le rythme du decompte disparait. */
function showCountdown(value) {
  const node = el.countdownValue;
  node.textContent = value > 0 ? value : '';
  node.style.animation = 'none';
  void node.offsetWidth;     // force le recalcul
  node.style.animation = '';
}

function showResult(payload) {
  const failures = (payload.results || []).filter((r) => !r.success);
  if (payload.exists) {
    el.resultPath.textContent = payload.path;
    el.resultPath.title = payload.path;
    el.result.classList.add('visible');
  }
  if (failures.length) {
    setStatus(failures.map((f) => `${f.name} : ${f.error}`).join(' · '),
              'error');
  } else {
    setStatus('Enregistrement terminé', 'ok');
  }
}

/* ---------- configuration du fournisseur IA ---------- */

let aiConfig = null;

/* Resume, sous le titre du panneau, quel fournisseur est actif et si les
 * donnees quittent la machine. L'utilisateur ne doit pas avoir a ouvrir
 * la boite de dialogue pour le savoir. */
function renderProviderLine() {
  const line = $('provider-line');
  if (!line || !aiConfig) return;

  const info = aiConfig.providers.find((p) => p.id === aiConfig.provider);
  const nom = info ? info.label : aiConfig.provider;

  if (!aiConfig.ready) {
    line.innerHTML = '<span class="offsite">' + nom + ' \u2014 non configur\u00e9</span>';
    return;
  }
  line.innerHTML = aiConfig.sends_offsite
    ? nom + ' \u00b7 <span class="offsite">les donn\u00e9es sortent du poste</span>'
    : nom + ' \u00b7 rien ne quitte la machine';
}

function renderAiModal() {
  if (!aiConfig) return;

  const select = $('ai-provider');
  select.innerHTML = '';
  aiConfig.providers.forEach((p) => {
    const suffixe = p.needs_key && !p.has_key ? ' \u2014 cl\u00e9 manquante' : '';
    select.add(new Option(p.label + suffixe, p.id));
  });
  select.value = aiConfig.provider;

  const info = aiConfig.providers.find((p) => p.id === aiConfig.provider);
  const note = $('ai-privacy');
  note.textContent = info ? info.note : '';
  note.className = 'modal-note ' + (info && info.local ? 'local' : 'offsite');

  $('ai-model').value = aiConfig.model || (info ? info.default_model : '');

  // Les modeles installes localement ne se devinent pas : les lister
  const hint = $('ai-model-hint');
  if (aiConfig.provider === 'ollama') {
    hint.textContent = aiConfig.local_models.length
      ? 'Install\u00e9s : ' + aiConfig.local_models.join(', ')
      : 'Ollama ne r\u00e9pond pas \u2014 est-il lanc\u00e9 ?';
  } else {
    hint.textContent = info ? 'Par d\u00e9faut : ' + info.default_model : '';
  }

  // Ollama tourne en local : aucune cle a saisir
  const keyField = $('ai-key-field');
  keyField.style.display = info && info.needs_key ? '' : 'none';
  const key = $('ai-key');
  key.value = '';
  key.placeholder = info && info.has_key
    ? 'Cl\u00e9 enregistr\u00e9e (' + info.masked_key + ') \u2014 laissez vide pour la garder'
    : 'Collez votre cl\u00e9';

  setAiStatus('');
}

function setAiStatus(message, kind) {
  const node = $('ai-status');
  node.textContent = message;
  node.className = 'modal-status' + (kind ? ' ' + kind : '');
}

/* Ancre l'ouverture d'une boite de dialogue sur le bouton qui l'a
 * declenchee : la boite grandit depuis ce bouton au lieu de surgir du
 * centre. La relation entre l'element clique et ce qui apparait reste
 * ainsi lisible. Sans declencheur, le centre est le repli (CSS). */
function ancrerModale(modalId, triggerId) {
  const modal = $(modalId);
  const trigger = $(triggerId);
  const card = modal && modal.querySelector('.modal-card');
  if (!card) return;
  if (!trigger) {
    card.style.removeProperty('--origin-x');
    card.style.removeProperty('--origin-y');
    modal.hidden = false;
    return;
  }
  const t = trigger.getBoundingClientRect();

  // La boite n'a pas de geometrie tant qu'elle est masquee : on la
  // rend visible mais transparente le temps de la mesurer, sinon
  // l'animation demarrerait avant que l'origine soit posee et la
  // premiere ouverture partirait du centre.
  card.style.visibility = 'hidden';
  modal.hidden = false;
  const c = card.getBoundingClientRect();
  // Coordonnees du declencheur, exprimees dans le repere de la boite
  card.style.setProperty('--origin-x',
    `${t.left + t.width / 2 - c.left}px`);
  card.style.setProperty('--origin-y',
    `${t.top + t.height / 2 - c.top}px`);
  // Rejoue l'animation depuis la bonne origine
  card.style.animation = 'none';
  void card.offsetWidth;            // force le recalcul
  card.style.removeProperty('animation');
  card.style.removeProperty('visibility');
}

async function openAiModal() {
  aiConfig = await call('get_ai_config');
  renderAiModal();
  ancrerModale('ai-modal', 'open-ai-config');
}

function closeAiModal() {
  $('ai-modal').hidden = true;
  // Ne jamais laisser une cle en clair dans le DOM apres fermeture
  $('ai-key').value = '';
}

async function saveAiConfig() {
  const provider = $('ai-provider').value;
  const model = $('ai-model').value.trim();
  const key = $('ai-key').value;

  setAiStatus('Enregistrement\u2026');
  const choix = await call('set_ai_provider', provider, model);
  if (!choix.ok) {
    setAiStatus(choix.error || '\u00c9chec', 'error');
    return;
  }

  // Champ laisse vide : la cle deja enregistree est conservee
  if (key) {
    const resultat = await call('set_ai_key', provider, key);
    if (!resultat.ok) {
      setAiStatus(resultat.error || '\u00c9chec', 'error');
      return;
    }
    aiConfig = resultat.config;
  } else {
    aiConfig = choix.config;
  }

  $('ai-key').value = '';
  renderAiModal();
  renderProviderLine();
  await refreshAiAvailability();
  setAiStatus('Enregistr\u00e9', 'ok');
}

async function testAiProvider() {
  setAiStatus('Test en cours\u2026');
  const resultat = await call('test_ai_provider');
  setAiStatus(resultat.ok ? 'R\u00e9ponse : ' + resultat.answer
                          : (resultat.error || '\u00c9chec'),
              resultat.ok ? 'ok' : 'error');
}

/* Les deux options qui dependent d'un fournisseur peuvent devenir
 * disponibles sans redemarrage : on relit l'etat apres configuration. */
async function refreshAiAvailability() {
  const state = await call('get_initial_state');
  if (!state || !state.ai) return;
  applyAiAvailability(state.ai.available);
}

function applyAiAvailability(available) {
  const raisons = {
    subtitles: 'N\u00e9cessite faster-whisper',
    privacy_blur: 'N\u00e9cessite easyocr',
    summary: 'N\u00e9cessite un fournisseur IA et les sous-titres',
    subtitle_fix: 'N\u00e9cessite un fournisseur IA et les sous-titres',
  };
  Object.entries(raisons).forEach(([cle, raison]) => {
    const wrapper = $('wrap-' + cle);
    const input = $(cle);
    if (!wrapper || !input) return;
    if (available[cle]) {
      wrapper.classList.remove('disabled');
      input.disabled = false;
    } else {
      disable('wrap-' + cle, cle, 'hint-' + cle, raison);
    }
  });
}

/* ---------- cablage des controles ---------- */

function bindCheckbox(id, key, onChange) {
  const input = $(id);
  if (!input) return;
  input.addEventListener('change', () => {
    call('set_option', key, input.checked);
    if (onChange) onChange(input.checked);
  });
}

function bindSelect(id, key) {
  const select = $(id);
  if (!select) return;
  select.addEventListener('change', () => call('set_option', key, select.value));
}

function disable(wrapperId, inputId, hintId, message) {
  const wrapper = $(wrapperId);
  const input = $(inputId);
  if (!wrapper || !input) return;
  wrapper.classList.add('disabled');
  input.disabled = true;
  input.checked = false;
  // Dire ce qui manque plutôt que de griser sans explication
  if (hintId && $(hintId)) $(hintId).textContent = message;
}

function populate(state) {
  el.profile.textContent = state.profile;
  if (state.version) $('version-tag').textContent = 'v' + state.version;
  el.hotkey.textContent = state.hotkey;
  el.hotkeyNote.textContent = state.hotkey_active
    ? 'fonctionne en arrière-plan'
    : (state.hotkey_error || 'raccourci indisponible');

  $('resolution').value = state.resolution;
  $('bitrate').value = state.bitrate;
  el.folder.textContent = state.save_directory;
  el.folder.title = state.save_directory;

  // Audio
  $('mic').checked = state.audio.mic_enabled;
  el.gain.value = state.audio.gain;
  el.gainValue.textContent = state.audio.gain;

  el.device.innerHTML = '';
  if (state.audio.devices.length === 0) {
    const option = new Option('Aucun microphone détecté', '-1');
    el.device.add(option);
    el.device.disabled = true;
    $('mic').checked = false;
    $('mic').disabled = true;
  } else {
    state.audio.devices.forEach((device) => {
      const label = device.name + (device.is_default ? ' (défaut)' : '');
      el.device.add(new Option(label, String(device.index)));
    });
    const selected = state.audio.selected_device;
    el.device.value = String(
      selected >= 0 ? selected
                    : (state.audio.devices.find((d) => d.is_default) || {}).index
                      ?? state.audio.devices[0].index);
  }

  $('system-audio').checked = state.audio.system_enabled;
  if (!state.audio.system_available) {
    disable('wrap-system-audio', 'system-audio', null, '');
    $('wrap-system-audio').querySelector('.check-hint').textContent =
      'Nécessite PyAudioWPatch';
  }

  // Smart Focus
  $('smart-focus').checked = state.smart_focus.enabled;
  if (!state.smart_focus.available) {
    disable('wrap-smart-focus', 'smart-focus', null, '');
    $('wrap-smart-focus').querySelector('.check-hint').textContent =
      'Nécessite pywin32';
  }

  // Options IA
  Object.entries(state.ai.options).forEach(([key, value]) => {
    if ($(key)) $(key).checked = value;
  });
  $('magic_cut_max').value = state.ai.magic_cut_max;
  $('delete_original').checked = state.ai.delete_original;

  applyAiAvailability(state.ai.available);
}

function wire() {
  el.record.addEventListener('click', async () => {
    el.result.classList.remove('visible');
    const result = await call('toggle_recording');
    if (result && result.ok === false && result.error) {
      setStatus(result.error, 'error');
    }
  });

  $('widget-stop').addEventListener('click', () => call('toggle_recording'));
  $('open-folder').addEventListener('click', () => call('open_output_folder'));

  el.folder.addEventListener('click', async () => {
    const result = await call('choose_folder');
    if (result && result.ok) {
      el.folder.textContent = result.path;
      el.folder.title = result.path;
    }
  });

  bindSelect('resolution', 'resolution');
  bindSelect('bitrate', 'bitrate');
  bindSelect('magic_cut_max', 'magic_cut_max');

  el.device.addEventListener('change', () =>
    call('set_option', 'audio_device_index', parseInt(el.device.value, 10)));

  el.gain.addEventListener('input', () => {
    el.gainValue.textContent = el.gain.value;
  });
  el.gain.addEventListener('change', () =>
    call('set_option', 'gain', parseFloat(el.gain.value)));

  bindCheckbox('mic', 'mic_enabled');
  bindCheckbox('system-audio', 'system_audio');
  bindCheckbox('smart-focus', 'smart_focus');
  ['privacy_blur', 'clean_canvas', 'overlay', 'subtitles', 'magic_cut',
   'thumbnails'].forEach((key) => bindCheckbox(key, key));
  bindCheckbox('delete_original', 'delete_original');
  bindCheckbox('summary', 'summary');
  bindCheckbox('subtitle_fix', 'subtitle_fix');

  $('open-plugins').addEventListener('click', openPluginsModal);
  $('plugins-close').addEventListener('click', closePluginsModal);
  $('plugins-folder').addEventListener('click',
    () => call('open_plugins_folder'));
  $('plugins-modal').addEventListener('click', (event) => {
    if (event.target === $('plugins-modal')) closePluginsModal();
  });

  $('version-tag').addEventListener('click', openUpdateModal);
  $('update-close').addEventListener('click', closeUpdateModal);
  $('update-later').addEventListener('click', closeUpdateModal);
  $('update-install').addEventListener('click', startUpdateInstall);
  $('update-modal').addEventListener('click', (event) => {
    if (event.target === $('update-modal')) closeUpdateModal();
  });

  $('open-ai-config').addEventListener('click', openAiModal);
  $('ai-close').addEventListener('click', closeAiModal);
  $('ai-save').addEventListener('click', saveAiConfig);
  $('ai-test').addEventListener('click', testAiProvider);
  $('ai-provider').addEventListener('change', () => {
    // Refleter immediatement l'avertissement du fournisseur choisi,
    // avant meme d'enregistrer
    const choisi = $('ai-provider').value;
    const info = aiConfig.providers.find((p) => p.id === choisi);
    if (info) {
      aiConfig = { ...aiConfig, provider: choisi, model: info.default_model };
      renderAiModal();
    }
  });
  // Clic hors de la carte : fermer, comme toute boite de dialogue
  $('ai-modal').addEventListener('click', (event) => {
    if (event.target === $('ai-modal')) closeAiModal();
  });

  // Le raccourci global passe par Windows, mais F9 pressé alors que la
  // fenêtre a le focus arriverait ici en double : on le laisse au
  // système, seul maître du basculement
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('ai-modal').hidden) {
      closeAiModal();
      return;
    }
    if (event.key === 'Escape' && !$('update-modal').hidden) {
      closeUpdateModal();
      return;
    }
    if (event.key === 'Escape' && !$('plugins-modal').hidden) {
      closePluginsModal();
      return;
    }
    if (event.key === 'Escape' && state === 'recording') {
      call('toggle_recording');
    }
  });
}

window.addEventListener('pywebviewready', async () => {
  wire();

  // Les informations d'abord : le montage du fond anime prend du temps
  // et retarderait l'affichage de l'interface
  aiConfig = await call('get_ai_config');
  renderProviderLine();

  const initial = await call('get_initial_state');
  if (initial) {
    populate(initial);
    applyState(initial.state);
  }

  // Fond anime : palette du theme, flux par defaut, repulsion au curseur
  const canvas = $('backdrop');
  if (canvas) {
    backdrop = new ShardField(canvas, {
      shardColor: '#F59E0B',      // ambre du theme
      accentColor: '#EF4444',     // rouge d'enregistrement, pour les ondes
      flow: 'stream',
      detail: 'balanced',
      density: 0.9,
      speed: 0.85,
      spread: 1.1,
      glow: 1,
      interaction: 'repel',
      interactionRadius: 1.4,
      rippleIntensity: 1,
      opacity: 0.42,
    });
    backdrop.mount();
  }

  // Signal de fin d'initialisation. Utilise par les verifications
  // automatisees pour ne pas deviner un delai ; absent en production, ou
  // l'appel echoue silencieusement.
  if (window.pywebview?.api?.page_prete) {
    try { window.pywebview.api.page_prete(); } catch (e) { /* ignore */ }
  }
});
