/* Lumina Recorder — logique de l'interface
 *
 * Ne contient aucune règle métier : tout passe par window.pywebview.api,
 * et l'état affiché vient des événements poussés par le pont Python.
 * Dupliquer ici la logique de l'enregistrement garantirait qu'elle
 * diverge du moteur.
 */

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
    el.widgetSize.textContent = formatSize(payload.bytes);
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
  }
};

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

/* ---------- câblage des contrôles ---------- */

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

  if (!state.ai.available.subtitles) {
    disable('wrap-subtitles', 'subtitles', 'hint-subtitles',
            'Nécessite faster-whisper');
  }
  if (!state.ai.available.privacy_blur) {
    disable('wrap-privacy_blur', 'privacy_blur', 'hint-privacy_blur',
            'Nécessite easyocr');
  }
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
  $('min').addEventListener('click', () => call('minimize'));
  $('close').addEventListener('click', () => call('close'));
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

  // Le raccourci global passe par Windows, mais F9 pressé alors que la
  // fenêtre a le focus arriverait ici en double : on le laisse au
  // système, seul maître du basculement
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state === 'recording') {
      call('toggle_recording');
    }
  });
}

window.addEventListener('pywebviewready', async () => {
  wire();
  const initial = await call('get_initial_state');
  if (initial) {
    populate(initial);
    applyState(initial.state);
  }
});
