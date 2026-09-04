/* Lumina Recorder — logique de l'interface capsule
 *
 * Ne contient aucune règle métier : tout passe par window.pywebview.api,
 * et l'état affiché vient des événements poussés par le pont Python.
 */

const $ = (id) => document.getElementById(id);

let state = 'idle';
let statusTimer = null;
let initial = null;     // dernier get_initial_state, relu après les réglages

/* ---------- utilitaires ---------- */

/* Chrono de la capsule : mm:ss, les heures en préfixe si besoin */
function formatCapsule(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
  const s = String(totalSeconds % 60).padStart(2, '0');
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
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
  const s = String(totalSeconds % 60).padStart(2, '0');
  $('widget-timer').textContent = `${m}:${s}`;
  $('widget-hours').textContent = h > 0 ? `${h}h` : '';
}

async function call(method, ...args) {
  try {
    return await window.pywebview.api[method](...args);
  } catch (error) {
    setStatus('Erreur interne : ' + error, 'error');
    return { ok: false, error: String(error) };
  }
}

/* Statut sous le chrono. Les erreurs restent ; le reste s'efface après
 * 6 s. `action` = {label, onClick} ajoute un lien (« Ouvrir »). */
function setStatus(message, kind, action) {
  const node = $('status');
  node.textContent = message;
  node.className = 'statut' + (kind ? ' ' + kind : '');
  if (action) {
    node.append(' · ');
    const lien = document.createElement('span');
    lien.className = 'action';
    lien.textContent = action.label;
    lien.addEventListener('click', action.onClick);
    node.append(lien);
  }
  clearTimeout(statusTimer);
  if (kind !== 'error') {
    statusTimer = setTimeout(() => {
      if (state === 'idle') { node.textContent = 'Prêt à enregistrer'; node.className = 'statut'; }
    }, 6000);
  }
}

/* ---------- rendu de l'état ---------- */

function applyState(next) {
  state = next;
  document.body.dataset.state = next;
  $('record').disabled = (next === 'processing');
  $('record').title = next === 'idle' ? "Commencer l'enregistrement (F9)" : "Arrêter l'enregistrement (F9)";
  if (next === 'idle') {
    $('timer').textContent = '00:00';
    updateWidgetTime(0);
    $('widget-size').textContent = '≈ 0 Mo';
    $('progress-bar').style.width = '0%';
    stopWave();
  }
  if (next === 'recording') startWave();
  if (next === 'pending') { fermerToutesLesFeuilles(); setStatus('Démarrage dans quelques secondes…'); }
  if (next === 'processing') { $('progress-step').textContent = 'Traitement…'; }
}

/* Point d'entrée des événements poussés par Python */
window.luminaEvent = function (message) {
  const { event, payload } = message;
  if (event === 'state') applyState(payload);
  else if (event === 'tick') {
    $('timer').textContent = formatCapsule(payload.seconds);
    updateWidgetTime(payload.seconds);
    $('widget-size').textContent = '≈ ' + formatSize(payload.bytes);
  }
  else if (event === 'countdown') showCountdown(payload);
  else if (event === 'progress') {
    if (payload.step) $('progress-step').textContent = payload.step;
    if (payload.value !== null && payload.value !== undefined) $('progress-bar').style.width = Math.round(payload.value * 100) + '%';
  }
  else if (event === 'error') setStatus(payload, 'error');
  else if (event === 'notice') setStatus(payload);
  else if (event === 'done') {
    // La dernière étape ne pousse pas toujours 1.0 : sans cela la barre
    // resterait figée juste avant la fin. Remise à 0 % au retour au repos.
    $('progress-bar').style.width = '100%';
    showResult(payload);
  }
  else if (event === 'webcam_preview') onWebcamPreview(payload);
  else if (event === 'update_available') onUpdateAvailable(payload);
  else if (event === 'update_progress') onUpdateProgress(payload);
  else if (event === 'update_launching') onUpdateLaunching();
  else if (event === 'update_error') onUpdateError(payload);
  else if (event === 'extension_progress') onExtensionProgress(payload);
  else if (event === 'extension_installed') refreshAiAvailability();
};

function showResult(payload) {
  const failures = (payload.results || []).filter((r) => !r.success);
  if (failures.length) {
    setStatus(failures.map((f) => `${f.name} : ${f.error}`).join(' · '), 'error');
  } else if (payload.exists) {
    setStatus('Enregistrement terminé', 'ok', { label: 'Ouvrir', onClick: () => call('open_output_folder') });
  } else {
    setStatus('Enregistrement traité', 'ok');
  }
}

/* Relance l'animation a chaque chiffre : sans cela le navigateur
 * reutilise l'animation en cours et le rythme du decompte disparait. */
function showCountdown(value) {
  const node = $('countdown-value');
  node.textContent = value > 0 ? value : '';
  node.style.animation = 'none';
  void node.offsetWidth;     // force le recalcul
  node.style.animation = '';
}

/* Onde au repos : 60 points, dessinés une fois */
function dessinerOndeRepos() {
  const zone = $('onde-repos');
  for (let i = 0; i < 60; i += 1) zone.append(document.createElement('i'));
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
  const canvas = $('widget-wave');
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

/* ---------- Feuilles ----------
 * Une pile : une sous-feuille (Fournisseur IA) glisse par-dessus la
 * feuille ouverte (Réglages). Échap ferme celle du dessus. */
const pile = [];

function feuilleOuverte() { return pile.length > 0; }

function ouvrirFeuille(id) {
  const feuille = $(id);
  if (!feuille || pile.includes(id)) return;
  // Une fermeture en cours masquerait la feuille qu'on vient de rouvrir
  clearTimeout(feuille._fermeture);
  pile.push(id);
  $('voile').hidden = false;
  feuille.hidden = false;
  feuille.style.zIndex = String(10 + pile.length);
  requestAnimationFrame(() => feuille.classList.add('ouverte'));
}

function fermerFeuille() {
  const id = pile.pop();
  if (!id) return;
  const feuille = $(id);
  feuille.classList.remove('ouverte');
  const cacher = () => {
    feuille.removeEventListener('transitionend', cacher);
    // Rouverte entre-temps : ne pas la masquer
    if (pile.includes(id)) return;
    feuille.hidden = true;
  };
  feuille.addEventListener('transitionend', cacher);
  feuille._fermeture = setTimeout(cacher, 260);   // repli si aucune transition (reduced-motion)
  if (id === 'sheet-ai') $('ai-key').value = '';   // jamais une clé en clair dans le DOM
  if (!pile.length) $('voile').hidden = true;
}

function fermerToutesLesFeuilles() { while (pile.length) fermerFeuille(); }

document.addEventListener('click', (event) => {
  if (event.target.classList.contains('feuille-fermer')) fermerFeuille();
  if (event.target.id === 'voile') fermerFeuille();
});

/* ---------- À venir (tâches 3 et 4) ----------
 *
 * Ces fonctions sont appelées par le noyau ci-dessus ; leur corps arrive
 * avec l'habillage des états et des feuilles. Déclarées vides ici pour
 * que la capsule au repos fonctionne seule, sans référence absente.
 */
function populateSettings() { /* tâche 4 */ }
function wireSettings() { /* tâche 4 */ }
function openExtensions() { ouvrirFeuille('sheet-extensions'); }   /* tâche 4 : remplissage */
function openUpdate() { ouvrirFeuille('sheet-update'); }           /* tâche 4 : remplissage */
async function chargerConfigIa() { /* tâche 4 */ }
function onWebcamPreview() { /* tâche 4 */ }
function onUpdateAvailable() { /* tâche 4 */ }
function onUpdateProgress() { /* tâche 4 */ }
function onUpdateLaunching() { /* tâche 4 */ }
function onUpdateError() { /* tâche 4 */ }
function onExtensionProgress() { /* tâche 4 */ }

/* Les deux options qui dependent d'un fournisseur peuvent devenir
 * disponibles sans redemarrage : on relit l'etat apres configuration. */
async function refreshAiAvailability() {
  const etat = await call('get_initial_state');
  if (!etat || !etat.ai) return;
  applyAiAvailability(etat.ai.available);
}

function applyAiAvailability(available) {
  // Pour les deux premieres, la raison est actionnable : un clic sur
  // l'indice ouvre la feuille ou l'extension s'installe. Dire
  // « necessite easyocr » a un utilisateur qui n'a pas pip ne l'aiderait
  // en rien.
  const raisons = {
    subtitles: 'Extension à installer — cliquez ici',
    privacy_blur: 'Extension à installer — cliquez ici',
    summary: 'Nécessite un fournisseur IA et les sous-titres',
    subtitle_fix: 'Nécessite un fournisseur IA et les sous-titres',
  };
  const installables = new Set(['subtitles', 'privacy_blur']);
  Object.entries(raisons).forEach(([cle, raison]) => {
    const wrapper = $('wrap-' + cle);
    const input = $(cle);
    const hint = $('hint-' + cle);
    if (!wrapper || !input) return;
    if (available[cle]) {
      wrapper.classList.remove('disabled');
      input.disabled = false;
      if (hint) {
        hint.classList.remove('hint-action');
        hint.onclick = null;
      }
    } else {
      disable('wrap-' + cle, cle, 'hint-' + cle, raison);
      if (hint && installables.has(cle)) {
        hint.classList.add('hint-action');
        // Affectation, pas addEventListener : cette fonction est
        // rappelee a chaque rafraichissement et empilerait les ecouteurs
        hint.onclick = (event) => {
          event.preventDefault();
          ouvrirFeuille('sheet-extensions');
        };
      }
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

// Previent AVANT l'enregistrement qu'une machine modeste risque de
// perdre des images. FilterChain desactive deja un filtre trop lent a
// chaud, mais l'utilisateur decouvre alors le probleme apres coup.
async function refreshCharge() {
  const zone = $('charge-warning');
  if (!zone) return;
  const options = {};
  ['privacy_blur', 'clean_canvas', 'overlay'].forEach((key) => {
    const input = $(key);
    options[key] = Boolean(input && input.checked);
  });
  try {
    const avis = await call('check_charge', options);
    const texte = (avis && avis.avertissement) || '';
    zone.textContent = texte;
    zone.hidden = !texte;
  } catch (e) {
    // Un avis indisponible ne doit rien casser : on se tait
    zone.hidden = true;
  }
}

/* Pastilles et bouton Smart Focus : une bascule = un set_option.
 *
 * Le câblage et l'état sont séparés : `bindPastille` est appelée une
 * seule fois depuis wire(), `appliquerPastille` autant de fois que
 * l'état est relu. Les mélanger empilerait un écouteur par relecture —
 * un clic déclencherait alors plusieurs set_option contradictoires. */
function bindPastille(id, key, inter) {
  const bouton = $(id);
  if (!bouton) return;
  bouton.dataset.inter = inter;
  // Mémorisé avant toute mise à jour : une pastille redevenue
  // disponible doit retrouver son infobulle, pas garder la raison du
  // grisage précédent
  bouton.dataset.titre = bouton.title;
  bouton.addEventListener('click', async () => {
    const actif = bouton.getAttribute('aria-pressed') !== 'true';
    bouton.setAttribute('aria-pressed', String(actif));
    await call('set_option', key, actif);
    // L'interrupteur correspondant de la feuille suit
    const champ = $(bouton.dataset.inter);
    if (champ) champ.checked = actif;
  });
}

/* Rejoue l'état d'une pastille : enfoncée ou non, et grisée avec sa
 * raison quand le matériel ou la dépendance manque. */
function appliquerPastille(id, actif, disponible, raison) {
  const bouton = $(id);
  if (!bouton) return;
  bouton.setAttribute('aria-pressed', String(actif && disponible));
  bouton.disabled = !disponible;
  bouton.title = disponible ? (bouton.dataset.titre || '') : raison;
}

function populate(s) {
  initial = s;
  $('version-tag').textContent = s.version ? 'v' + s.version : 'v—';
  $('profile').textContent = s.profile || '';
  $('hotkey').textContent = s.hotkey;
  $('hotkey-settings').textContent = s.hotkey;
  $('hotkey-note').textContent = s.hotkey_active ? 'fonctionne en arrière-plan' : (s.hotkey_error || 'raccourci indisponible');
  $('countdown-format').textContent = `${s.resolution.replace('x', '×')} · ${s.fps} im/s · MP4`;
  $('widget-res').textContent = s.resolution.replace('x', '×');

  // État seulement : le câblage a eu lieu une fois dans wire()
  appliquerPastille('pill-mic', s.audio.mic_enabled,
    s.audio.devices.length > 0, 'Aucun microphone détecté');
  appliquerPastille('pill-system', s.audio.system_enabled,
    s.audio.system_available, 'Nécessite PyAudioWPatch');
  appliquerPastille('pill-webcam', s.webcam.enabled,
    s.webcam.available, 'Aucune webcam détectée');
  appliquerPastille('smart-focus-btn', s.smart_focus.enabled,
    s.smart_focus.available, 'Nécessite pywin32');

  populateSettings(s);     // tâche 4
}

function wire() {
  $('record').addEventListener('click', async () => {
    const result = await call('toggle_recording');
    if (result && result.ok === false && result.error) setStatus(result.error, 'error');
  });
  $('widget-stop').addEventListener('click', () => call('toggle_recording'));
  $('open-folder').addEventListener('click', () => call('open_output_folder'));
  $('minimize').addEventListener('click', () => call('minimize'));
  $('close').addEventListener('click', () => call('close'));
  $('open-settings').addEventListener('click', () => ouvrirFeuille('sheet-settings'));
  $('open-extensions').addEventListener('click', openExtensions);   // tâche 4
  $('update-pill').addEventListener('click', openUpdate);           // tâche 4

  // Une seule fois : populate() ne fera plus que rejouer leur état
  bindPastille('pill-mic', 'mic_enabled', 'mic');
  bindPastille('pill-system', 'system_audio', 'system-audio');
  bindPastille('pill-webcam', 'webcam_enabled', 'webcam-enabled');
  bindPastille('smart-focus-btn', 'smart_focus', 'smart-focus');

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (feuilleOuverte()) { fermerFeuille(); return; }
    if (state === 'pending') call('stop_recording');        // annule le décompte
    else if (state === 'recording') call('toggle_recording');
  });

  wireSettings();          // tâche 4
}

window.addEventListener('pywebviewready', async () => {
  dessinerOndeRepos();
  wire();
  const s = await call('get_initial_state');
  if (s) { populate(s); applyState(s.state); }
  await chargerConfigIa();   // tâche 4 : ligne du fournisseur
  if (window.pywebview?.api?.page_prete) {
    try { window.pywebview.api.page_prete(); } catch (e) { /* ignore */ }
  }
});
