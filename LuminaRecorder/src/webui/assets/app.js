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
  // Sans statut, la puce du raccourci resterait seule sous le chrono
  $('hotkey').hidden = !message;
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
      if (state === 'idle') { node.textContent = 'Prêt à enregistrer'; node.className = 'statut'; $('hotkey').hidden = false; }
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
    // La dernière image de la session précédente ne doit pas réapparaître
    // une fraction de seconde au début de la suivante
    $('widget-cam').hidden = true;
    $('widget-cam-img').removeAttribute('src');
  }
  if (next === 'recording') startWave();
  if (next === 'pending') {
    fermerToutesLesFeuilles();
    setStatus('Démarrage dans quelques secondes…');
    // Le pied dit ce qui va être enregistré au moment où il est encore
    // possible d'annuler : webcam prête ou non, et le format.
    const cam = $('countdown-webcam');
    const actif = initial && initial.webcam.enabled && initial.webcam.available;
    cam.innerHTML = '';
    const point = document.createElement('span');
    point.className = 'point-ok' + (actif ? '' : ' absent');
    cam.append(point, actif ? 'Webcam prête' : 'Sans webcam');
  }
  if (next === 'processing') {
    $('progress-step').textContent = 'Traitement…';
    // « Démarrage dans quelques secondes… », posé au décompte, restait
    // affiché sous le chrono pendant tout l'encodage : l'étape en cours
    // est déjà dite au-dessus de la barre, la ligne de statut se tait.
    setStatus('');
  }
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

/* Vignette webcam du widget : JPEG base64 poussé par le pont à 8 im/s.
 * Absente si la webcam est inactive : la colonne de gauche s'étend.
 *
 * La forme suit le réglage (rond, carré arrondi, carré) pour que
 * l'aperçu ressemble à ce qui sera incrusté dans la vidéo. */
function onWebcamPreview(payload) {
  if (state !== 'recording' || !payload || !payload.image) return;
  const cadre = $('widget-cam');
  if (cadre.hidden) {
    cadre.hidden = false;
    cadre.className = 'vignette forme-' + ((initial && initial.webcam.forme) || 'rond');
  }
  $('widget-cam-img').src = 'data:image/jpeg;base64,' + payload.image;
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
  const step = 5;
  const bars = Math.ceil(width / step) + 2;

  ctx.clearRect(0, 0, width, height);
  // Barres pleines et sombres sur la bande ambre, comme la maquette :
  // un noir translucide laissait passer l'ambre et grisait le trace.
  ctx.fillStyle = '#0D0E11';

  for (let i = 0; i < bars; i += 1) {
    const x = i * step - (waveOffset % step);
    const seed = i + Math.floor(waveOffset / step);
    // Somme de sinusoides dephasees : irregulier a l'oeil, sans hasard,
    // donc stable d'une image a l'autre quand la bande defile
    const amplitude =
      Math.abs(Math.sin(seed * 0.7)) * 0.45 +
      Math.abs(Math.sin(seed * 0.31 + 1.2)) * 0.35 +
      Math.abs(Math.sin(seed * 1.9 + 0.4)) * 0.2;
    const barHeight = Math.max(2, amplitude * height * 0.85);
    ctx.fillRect(x, middle - barHeight / 2, 2, barHeight);
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
  const id = pile[pile.length - 1];
  if (!id) return;
  // Pas de fermeture pendant le téléchargement d'une mise à jour, par
  // quelque geste que ce soit : l'utilisateur doit voir si son
  // installateur est complet ou en échec.
  if (id === 'sheet-update' && updateDownloading) return;
  pile.pop();
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

/* S'arrête si une feuille refuse de partir (mise à jour en cours) :
 * sans ce garde-fou, la boucle tournerait sans fin. */
function fermerToutesLesFeuilles() {
  let reste = pile.length;
  while (reste) {
    fermerFeuille();
    if (pile.length === reste) return;
    reste = pile.length;
  }
}

document.addEventListener('click', (event) => {
  if (event.target.classList.contains('feuille-fermer')) fermerFeuille();
  if (event.target.id === 'voile') fermerFeuille();
});

/* ---------- Réglages ---------- */

function montrerOnglet(nom) {
  document.querySelectorAll('#onglets button').forEach((b) => b.classList.toggle('actif', b.dataset.tab === nom));
  ['capture', 'audio', 'webcam', 'ia'].forEach((t) => { $('tab-' + t).hidden = (t !== nom); });
  $('sheet-settings').querySelector('.feuille-corps').scrollTop = 0;
}

/* Contrôle segmenté ou grille de coins : un clic = une valeur */
function bindSegment(id, key, onChange) {
  const zone = $(id);
  if (!zone) return;
  zone.querySelectorAll('button').forEach((b) => b.addEventListener('click', async () => {
    zone.querySelectorAll('button').forEach((x) => x.classList.toggle('sel', x === b));
    await call('set_option', key, b.dataset.value);
    if (onChange) onChange(b.dataset.value);
  }));
}

function setSegment(id, value) {
  const zone = $(id);
  if (!zone) return;
  zone.querySelectorAll('button').forEach((b) => b.classList.toggle('sel', b.dataset.value === value));
}

function populateSettings(s) {
  $('resolution').value = s.resolution;
  $('bitrate').value = s.bitrate;
  $('folder').textContent = s.save_directory; $('folder').title = s.save_directory;
  $('smart-focus').checked = s.smart_focus.enabled;
  if (!s.smart_focus.available) { $('smart-focus').disabled = true; $('smart-focus-hint').textContent = 'Nécessite pywin32'; }

  $('mic').checked = s.audio.mic_enabled;
  $('gain').value = s.audio.gain; $('gain-value').textContent = s.audio.gain;
  const device = $('device'); device.innerHTML = '';
  if (!s.audio.devices.length) {
    device.add(new Option('Aucun microphone détecté', '-1')); device.disabled = true;
    $('mic').checked = false; $('mic').disabled = true;
  } else {
    s.audio.devices.forEach((d) => device.add(new Option(d.name + (d.is_default ? ' (défaut)' : ''), String(d.index))));
    const sel = s.audio.selected_device;
    device.value = String(sel >= 0 ? sel : ((s.audio.devices.find((d) => d.is_default) || s.audio.devices[0]).index));
  }
  $('system-audio').checked = s.audio.system_enabled;
  if (!s.audio.system_available) { $('system-audio').disabled = true; $('system-audio-hint').textContent = 'Nécessite PyAudioWPatch'; }

  // Webcam
  const w = s.webcam;
  $('webcam-enabled').checked = w.enabled && w.available;
  const cams = $('webcam-device'); cams.innerHTML = '';
  if (!w.available) {
    cams.add(new Option('Aucune webcam détectée', '-1')); cams.disabled = true;
    $('webcam-enabled').disabled = true; $('webcam-test').disabled = true;
    $('webcam-hint').textContent = 'Aucune webcam détectée';
  } else {
    w.devices.forEach((d) => cams.add(new Option(d.nom, String(d.index))));
    cams.value = String(w.devices.some((d) => d.index === w.device) ? w.device : w.devices[0].index);
  }
  setSegment('webcam-forme', w.forme); setSegment('webcam-coin', w.coin); setSegment('webcam-taille', w.taille);
  $('webcam-miroir').checked = w.miroir;
  $('webcam-preview').className = 'apercu forme-' + w.forme;

  // IA
  Object.entries(s.ai.options).forEach(([key, value]) => { if ($(key)) $(key).checked = value; });
  $('magic_cut_max').value = s.ai.magic_cut_max;
  $('delete_original').checked = s.ai.delete_original;
  applyAiAvailability(s.ai.available);
  refreshCharge();
}

/* Interrupteur de la feuille : persiste et reflète sur la pastille */
function bindInter(id, key, pastilleId) {
  const input = $(id);
  if (!input) return;
  input.addEventListener('change', async () => {
    await call('set_option', key, input.checked);
    if (pastilleId) $(pastilleId).setAttribute('aria-pressed', String(input.checked));
    if (initial && key === 'webcam_enabled') initial.webcam.enabled = input.checked;
  });
}

/* L'appel bloque jusqu'à 5 s le temps d'ouvrir la caméra : le bouton
 * doit le dire, sinon un clic sans réaction passe pour une panne. */
async function testerWebcam() {
  const bouton = $('webcam-test');
  const apercu = $('webcam-preview');
  bouton.disabled = true; bouton.textContent = 'Ouverture…';
  const r = await call('test_webcam', parseInt($('webcam-device').value, 10));
  bouton.disabled = false; bouton.textContent = 'Tester';
  if (r && r.ok) {
    apercu.style.backgroundImage = `url(data:image/jpeg;base64,${r.image})`;
    setTimeout(() => { apercu.style.backgroundImage = ''; }, 2000);
  } else {
    $('webcam-hint').textContent = (r && r.error) || 'Webcam indisponible';
  }
}

function wireSettings() {
  document.querySelectorAll('#onglets button').forEach((b) => b.addEventListener('click', () => montrerOnglet(b.dataset.tab)));
  bindSelect('resolution', 'resolution');
  bindSelect('bitrate', 'bitrate');
  bindSelect('magic_cut_max', 'magic_cut_max');
  $('folder').addEventListener('click', async () => {
    const r = await call('choose_folder');
    if (r && r.ok) { $('folder').textContent = r.path; $('folder').title = r.path; }
  });
  bindInter('smart-focus', 'smart_focus', 'smart-focus-btn');
  bindInter('mic', 'mic_enabled', 'pill-mic');
  bindInter('system-audio', 'system_audio', 'pill-system');
  bindInter('webcam-enabled', 'webcam_enabled', 'pill-webcam');
  bindInter('webcam-miroir', 'webcam_miroir', null);
  $('device').addEventListener('change', () => call('set_option', 'audio_device_index', parseInt($('device').value, 10)));
  $('webcam-device').addEventListener('change', () => call('set_option', 'webcam_device', parseInt($('webcam-device').value, 10)));
  $('gain').addEventListener('input', () => { $('gain-value').textContent = $('gain').value; });
  $('gain').addEventListener('change', () => call('set_option', 'gain', parseFloat($('gain').value)));
  bindSegment('webcam-forme', 'webcam_forme', (v) => { $('webcam-preview').className = 'apercu forme-' + v; if (initial) initial.webcam.forme = v; });
  bindSegment('webcam-coin', 'webcam_coin');
  bindSegment('webcam-taille', 'webcam_taille');
  $('webcam-test').addEventListener('click', testerWebcam);
  ['privacy_blur', 'clean_canvas', 'overlay', 'subtitles', 'magic_cut', 'thumbnails'].forEach((k) => bindCheckbox(k, k, refreshCharge));
  bindCheckbox('delete_original', 'delete_original');
  bindCheckbox('summary', 'summary');
  bindCheckbox('subtitle_fix', 'subtitle_fix');
  $('open-ai-config').addEventListener('click', openAiSheet);
  wireExtensions(); wireAi(); wireUpdate();
}

/* ---------- Mise à jour ----------
 *
 * L'application vérifie au démarrage s'il existe une version plus
 * récente. La pastille de l'en-tête passe en ambre ; le reste ne bouge
 * pas — une mise à jour ne doit jamais interrompre ce que l'utilisateur
 * est en train de faire.
 */

let updateInfo = null;
let updateDownloading = false;

function onUpdateAvailable(payload) {
  updateInfo = payload;
  const p = $('update-pill');
  p.textContent = payload.version + ' disponible';
  p.hidden = false;
}

function openUpdate() {
  if (!updateInfo) return;
  $('update-version').textContent = updateInfo.version;
  $('update-size').textContent = updateInfo.size ? '(' + formatSize(updateInfo.size) + ')' : '';
  const notes = $('update-notes');
  notes.textContent = updateInfo.notes || '';
  notes.hidden = !updateInfo.notes;
  $('update-status').textContent = '';
  $('update-progress').hidden = true;
  $('update-install').disabled = false;
  $('update-later').disabled = false;
  ouvrirFeuille('sheet-update');
}

async function startUpdateInstall() {
  const result = await call('install_update');
  if (!result || !result.ok) {
    $('update-status').textContent = (result && result.error) || 'Mise à jour impossible';
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
  $('update-status').textContent = "L'installateur démarre — Lumina va se fermer.";
}

function onUpdateError(message) {
  updateDownloading = false;
  $('update-install').disabled = false;
  $('update-later').disabled = false;
  $('update-progress').hidden = true;
  $('update-status').textContent = message;
}

function wireUpdate() {
  // `fermerFeuille` refuse déjà de partir pendant le téléchargement
  $('update-later').addEventListener('click', fermerFeuille);
  $('update-install').addEventListener('click', startUpdateInstall);
}

/* ---------- Extensions et plugins ----------
 *
 * La liste est construite en créant des noeuds, jamais par innerHTML
 * avec du texte de plugin : un nom de plugin est du contenu tiers, il
 * ne doit pas pouvoir injecter du balisage dans l'interface.
 */

const extensionEnCours = new Set();

async function openExtensions() {
  await Promise.all([renderExtensions(), renderPlugins()]);
  ouvrirFeuille('sheet-extensions');
}

function wireExtensions() {
  $('plugins-folder').addEventListener('click', () => call('open_plugins_folder'));
}

/* Whisper et l'OCR ne sont plus livrés avec l'application : ils pesaient
 * 700 Mo sur un socle qui en fait 250. Cette liste est le recours de
 * l'utilisateur venu d'une version où ils étaient embarqués — sans elle,
 * sa fonction disparaîtrait derrière une case grisée. */
async function renderExtensions() {
  const data = await call('get_extensions');
  const liste = $('extension-list');
  liste.textContent = '';

  if (!data || !data.ok) {
    const vide = document.createElement('p');
    vide.className = 'plugin-vide';
    vide.textContent = 'Catalogue indisponible' + (data && data.error ? ' : ' + data.error : '');
    liste.append(vide);
    return;
  }

  for (const ext of data.extensions) {
    const ligne = document.createElement('div');
    ligne.className = 'plugin-item ext-item';
    ligne.dataset.cle = ext.cle;

    const info = document.createElement('div');
    info.className = 'plugin-info';

    const titre = document.createElement('div');
    titre.className = 'plugin-nom';
    titre.textContent = ext.nom;

    const detail = document.createElement('div');
    detail.className = 'plugin-detail';
    // Les deux chiffres comptent : ce qu'on télécharge, et l'espace
    // qu'on y laisse — sur une machine à faible stockage, c'est le
    // second qui décide
    detail.textContent = ext.installee
      ? ext.description + ' · ' + ext.disque_mo + ' Mo sur le disque'
      : ext.description + ' · ' + ext.taille_mo + ' Mo à télécharger, '
        + ext.disque_mo + ' Mo sur le disque';

    const progres = document.createElement('div');
    progres.className = 'progression ext-progress';
    progres.hidden = true;
    const piste = document.createElement('div');
    piste.className = 'progression-piste';
    const barre = document.createElement('div');
    barre.className = 'progression-barre';
    piste.append(barre);
    const label = document.createElement('span');
    label.className = 'progression-etape';
    label.textContent = '0 %';
    progres.append(piste, label);

    info.append(titre, detail, progres);
    ligne.append(info);

    if (ext.installee) {
      const badge = document.createElement('span');
      badge.className = 'ext-badge';
      badge.textContent = 'Installée';
      ligne.append(badge);
    } else {
      const bouton = document.createElement('button');
      bouton.className = 'bouton';
      bouton.textContent = 'Installer';
      bouton.disabled = extensionEnCours.has(ext.cle);
      bouton.addEventListener('click', () => installExtension(ext, ligne));
      ligne.append(bouton);
    }

    liste.append(ligne);
  }
}

async function installExtension(ext, ligne) {
  if (extensionEnCours.has(ext.cle)) return;
  extensionEnCours.add(ext.cle);

  const bouton = ligne.querySelector('button');
  const progres = ligne.querySelector('.ext-progress');
  const detail = ligne.querySelector('.plugin-detail');
  bouton.disabled = true;
  bouton.textContent = 'Téléchargement…';
  progres.hidden = false;
  detail.classList.remove('ext-echec');

  // L'appel bloque jusqu'à la fin ; la progression arrive par
  // événements pendant ce temps
  const resultat = await call('install_extension', ext.cle);
  extensionEnCours.delete(ext.cle);

  if (resultat && resultat.ok) {
    await renderExtensions();
    $('plugins-status').textContent = ext.nom + ' installée';
    return;
  }

  progres.hidden = true;
  bouton.disabled = false;
  bouton.textContent = 'Réessayer';
  detail.classList.add('ext-echec');
  detail.textContent = (resultat && resultat.error) || 'Installation impossible';
}

function onExtensionProgress(payload) {
  const ligne = document.querySelector('.ext-item[data-cle="' + payload.cle + '"]');
  if (!ligne) return;
  const pct = Math.round((payload.progress || 0) * 100);
  ligne.querySelector('.progression-barre').style.width = pct + '%';
  ligne.querySelector('.progression-etape').textContent = pct + ' %';
  const bouton = ligne.querySelector('button');
  if (bouton && pct >= 95) bouton.textContent = 'Installation…';
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
    vide.textContent = 'Aucun plugin installé. Déposez un fichier .py dans le dossier des plugins.';
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
      : (p.description || 'Aucune description') + ' · ' + p.auteur + ' · v' + p.version;

    info.append(titre, detail);
    ligne.append(info);

    if (!p.erreur) {
      const etiquette = document.createElement('label');
      etiquette.className = 'inter';
      const inter = document.createElement('input');
      inter.type = 'checkbox';
      inter.checked = p.actif;
      inter.setAttribute('aria-label', 'Activer ' + p.nom);
      inter.addEventListener('change', async () => {
        await call('set_plugin_actif', p.identifiant, inter.checked);
        $('plugins-status').textContent = 'Prend effet au prochain enregistrement';
      });
      etiquette.append(inter, document.createElement('span'));
      ligne.append(etiquette);
    }

    liste.append(ligne);
  }
}

/* ---------- Configuration du fournisseur IA ---------- */

let aiConfig = null;

async function chargerConfigIa() {
  aiConfig = await call('get_ai_config');
  renderProviderLine();
}

async function openAiSheet() {
  aiConfig = await call('get_ai_config');
  renderAiSheet();
  ouvrirFeuille('sheet-ai');
}

function wireAi() {
  $('ai-save').addEventListener('click', saveAiConfig);
  $('ai-test').addEventListener('click', testAiProvider);
  $('ai-provider').addEventListener('change', () => {
    // Refléter immédiatement l'avertissement du fournisseur choisi,
    // avant même d'enregistrer
    if (!aiConfig) return;
    const choisi = $('ai-provider').value;
    const info = aiConfig.providers.find((p) => p.id === choisi);
    if (info) {
      aiConfig = { ...aiConfig, provider: choisi, model: info.default_model };
      renderAiSheet();
    }
  });
}

/* Résume, sous « Fournisseur », quel fournisseur est actif et si les
 * données quittent la machine. L'utilisateur ne doit pas avoir à ouvrir
 * la sous-feuille pour le savoir.
 *
 * Construit par noeuds : le libellé du fournisseur vient du pont, il ne
 * doit jamais passer par innerHTML. */
function renderProviderLine() {
  const line = $('provider-line');
  if (!line || !aiConfig) return;

  const info = aiConfig.providers.find((p) => p.id === aiConfig.provider);
  const nom = info ? info.label : aiConfig.provider;
  line.textContent = '';

  if (!aiConfig.ready) {
    const alerte = document.createElement('span');
    alerte.className = 'offsite';
    alerte.textContent = nom + ' — non configuré';
    line.append(alerte);
    return;
  }
  if (aiConfig.sends_offsite) {
    const alerte = document.createElement('span');
    alerte.className = 'offsite';
    alerte.textContent = 'les données sortent du poste';
    line.append(nom + ' · ', alerte);
  } else {
    line.textContent = nom + ' · rien ne quitte la machine';
  }
}

function renderAiSheet() {
  if (!aiConfig) return;

  const select = $('ai-provider');
  select.innerHTML = '';
  aiConfig.providers.forEach((p) => {
    const suffixe = p.needs_key && !p.has_key ? ' — clé manquante' : '';
    select.add(new Option(p.label + suffixe, p.id));
  });
  select.value = aiConfig.provider;

  const info = aiConfig.providers.find((p) => p.id === aiConfig.provider);
  const note = $('ai-privacy');
  note.textContent = info ? info.note : '';
  note.className = 'note ' + (info && info.local ? 'local' : 'offsite');

  $('ai-model').value = aiConfig.model || (info ? info.default_model : '');

  // Les modèles installés localement ne se devinent pas : les lister
  const hint = $('ai-model-hint');
  if (aiConfig.provider === 'ollama') {
    hint.textContent = aiConfig.local_models.length
      ? 'Installés : ' + aiConfig.local_models.join(', ')
      : 'Ollama ne répond pas — est-il lancé ?';
  } else {
    hint.textContent = info ? 'Par défaut : ' + info.default_model : '';
  }

  // Ollama tourne en local : aucune clé à saisir
  $('ai-key-field').hidden = !(info && info.needs_key);
  const key = $('ai-key');
  key.value = '';
  key.placeholder = info && info.has_key
    ? 'Clé enregistrée (' + info.masked_key + ') — laissez vide pour la garder'
    : 'Collez votre clé';

  setAiStatus('');
}

function setAiStatus(message, kind) {
  const node = $('ai-status');
  node.textContent = message;
  node.className = 'etat-action' + (kind ? ' ' + kind : '');
}

async function saveAiConfig() {
  const provider = $('ai-provider').value;
  const model = $('ai-model').value.trim();
  const key = $('ai-key').value;

  setAiStatus('Enregistrement…');
  const choix = await call('set_ai_provider', provider, model);
  if (!choix.ok) {
    setAiStatus(choix.error || 'Échec', 'error');
    return;
  }

  // Champ laissé vide : la clé déjà enregistrée est conservée
  if (key) {
    const resultat = await call('set_ai_key', provider, key);
    if (!resultat.ok) {
      setAiStatus(resultat.error || 'Échec', 'error');
      return;
    }
    aiConfig = resultat.config;
  } else {
    aiConfig = choix.config;
  }

  $('ai-key').value = '';
  renderAiSheet();
  renderProviderLine();
  await refreshAiAvailability();
  setAiStatus('Enregistré', 'ok');
}

async function testAiProvider() {
  setAiStatus('Test en cours…');
  const resultat = await call('test_ai_provider');
  setAiStatus(resultat.ok ? 'Réponse : ' + resultat.answer : (resultat.error || 'Échec'),
              resultat.ok ? 'ok' : 'error');
}

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
