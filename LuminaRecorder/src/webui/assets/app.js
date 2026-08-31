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
  compactTimer: $('compact-timer'),
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
  el.body.classList.toggle('compact', next === 'recording');

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
    el.compactTimer.textContent = '00:00:00';
  }
  if (next === 'pending') {
    setStatus('Cliquez sur la fenêtre à enregistrer…');
  }
}

/* Point d'entrée des événements poussés par Python */
window.luminaEvent = function (message) {
  const { event, payload } = message;

  if (event === 'state') {
    applyState(payload);
  } else if (event === 'tick') {
    const text = formatDuration(payload);
    el.timer.textContent = text;
    el.compactTimer.textContent = text;
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

  $('compact-stop').addEventListener('click', () => call('toggle_recording'));
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
