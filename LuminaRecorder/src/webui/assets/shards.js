/* Lumina Recorder — fond animé « éclats »
 *
 * Inspiré du composant AeroShards (React Bits). L'original est un moteur
 * WebGPU : ~1500 lignes de shaders WGSL, rendu 3D, bloom, aberration
 * chromatique, dithering, ASCII. Rien de tout cela n'est transposable en
 * HTML — c'est du calcul GPU, pas du balisage.
 *
 * Ce module reprend ce qui porte réellement le rendu à l'écran, en
 * Canvas 2D : des éclats orientés le long d'un flux, une profondeur, une
 * lueur, une répulsion au curseur et des ondes au clic. Il conserve les
 * noms de propriétés de l'original (shardColor, density, speed, spread,
 * flow, interaction…) pour rester réglable de la même façon.
 *
 * Ce qui est délibérément absent : aberration chromatique, grain, ASCII,
 * dithering. Sur le fond d'une application qu'on regarde tous les jours,
 * ces effets coûtent des ressources sans rien apporter à la lecture.
 *
 * CONTRAINTE PROPRE À LUMINA : ce fond s'arrête complètement pendant un
 * enregistrement. Une animation permanente vole des cycles à la capture
 * d'écran, ce que le projet s'attache justement à éviter (budget par
 * image des filtres). Voir `pause()`.
 */

const FLOWS = { stream: 0, vortex: 1, ribbon: 2 };
const INTERACTIONS = { none: 0, repel: 1, attract: 2 };
const DETAIL_PRESETS = {
  bold: { count: 0.58, size: 1.32 },
  balanced: { count: 1.0, size: 0.96 },
  fine: { count: 1.15, size: 0.7 },
};

const DEFAULTS = {
  backgroundColor: '#131417',
  shardColor: '#F59E0B',
  accentColor: '#EF4444',
  flow: 'stream',
  detail: 'balanced',
  density: 1.0,
  shardSize: 1.0,
  scale: 1,
  spread: 1,
  depth: 1,
  speed: 1,
  spin: 1,
  stretch: 1,
  glow: 1,
  interaction: 'repel',
  interactionRadius: 1.5,
  interactionStrength: 0.5,
  rippleIntensity: 1,
  opacity: 0.5,
};

// Plafond de particules : au-delà, le coût de dessin devient perceptible
// sur une machine modeste, sans gain visuel notable.
const MAX_SHARDS = 140;
const RIPPLE_SPEED = 520;      // pixels par seconde
const RIPPLE_TAIL = 1.6;       // secondes

function hexToRgb(hex) {
  const clean = String(hex).replace('#', '');
  const full = clean.length === 3
    ? clean.split('').map((c) => c + c).join('')
    : clean;
  const value = parseInt(full, 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export class ShardField {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: true });
    this.options = { ...DEFAULTS, ...options };

    this.shards = [];
    this.ripples = [];
    this.pointer = { x: -9999, y: -9999, active: false };
    this.frame = null;
    this.lastTime = 0;
    this.paused = false;
    this.width = 0;
    this.height = 0;

    this.shardRgb = hexToRgb(this.options.shardColor);
    this.accentRgb = hexToRgb(this.options.accentColor);

    this._onResize = () => this.resize();
    this._onPointerMove = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.pointer.x = e.clientX - rect.left;
      this.pointer.y = e.clientY - rect.top;
      this.pointer.active = true;
    };
    this._onPointerLeave = () => { this.pointer.active = false; };
    this._onPointerDown = (e) => {
      if (!this.options.rippleIntensity) return;
      const rect = this.canvas.getBoundingClientRect();
      this.addRipple(e.clientX - rect.left, e.clientY - rect.top);
    };
    this._onVisibility = () => {
      // Une fenêtre masquée continue de consommer si on ne l'arrête pas
      if (document.hidden) this.stop();
      else if (!this.paused) this.start();
    };
  }

  /* ---------- cycle de vie ---------- */

  mount() {
    this.resize();
    window.addEventListener('resize', this._onResize);
    window.addEventListener('pointermove', this._onPointerMove);
    window.addEventListener('pointerdown', this._onPointerDown);
    document.addEventListener('pointerleave', this._onPointerLeave);
    document.addEventListener('visibilitychange', this._onVisibility);

    // prefers-reduced-motion n'est pas une préférence esthétique : une
    // animation permanente est un problème réel pour qui souffre de
    // troubles vestibulaires. On dessine une image fixe.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.draw(0);
      return;
    }
    this.start();
  }

  destroy() {
    this.stop();
    window.removeEventListener('resize', this._onResize);
    window.removeEventListener('pointermove', this._onPointerMove);
    window.removeEventListener('pointerdown', this._onPointerDown);
    document.removeEventListener('pointerleave', this._onPointerLeave);
    document.removeEventListener('visibilitychange', this._onVisibility);
  }

  start() {
    if (this.frame !== null) return;
    this.lastTime = performance.now();
    const loop = (now) => {
      const elapsed = Math.min(0.05, (now - this.lastTime) / 1000);
      this.lastTime = now;
      this.update(elapsed);
      this.draw(now / 1000);
      this.frame = requestAnimationFrame(loop);
    };
    this.frame = requestAnimationFrame(loop);
  }

  stop() {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }

  /** Gèle le champ. Appelé pendant un enregistrement : une animation
   *  permanente vole des cycles à la capture d'écran. */
  pause() {
    this.paused = true;
    this.stop();
  }

  resume() {
    this.paused = false;
    if (!document.hidden
        && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.start();
    }
  }

  /* ---------- géométrie ---------- */

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    // Le rendu suit la densité de pixels de l'écran, sinon le tracé est
    // flou sur un affichage mis à l'échelle
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.populate();
  }

  populate() {
    const preset = DETAIL_PRESETS[this.options.detail] || DETAIL_PRESETS.balanced;
    // Le nombre suit la surface : une grande fenêtre ne doit pas paraître
    // vide, une petite ne doit pas être saturée
    const area = (this.width * this.height) / (1280 * 720);
    const target = clamp(
      Math.round(70 * area * preset.count * this.options.density),
      24, MAX_SHARDS);

    this.shards = Array.from({ length: target }, (_, i) => this.makeShard(i));
  }

  makeShard(index) {
    const preset = DETAIL_PRESETS[this.options.detail] || DETAIL_PRESETS.balanced;
    // Profondeur : les éclats proches sont plus grands, plus opaques et
    // se déplacent plus vite — c'est ce qui donne le volume
    const depth = Math.random();
    const size = (7 + Math.random() * 16)
      * preset.size * this.options.shardSize * this.options.scale
      * (0.55 + depth * 0.9);

    return {
      index,
      phase: Math.random(),
      lane: Math.random() * 2 - 1,
      depth,
      size,
      spin: (Math.random() * 2 - 1) * 0.8,
      angle: Math.random() * Math.PI * 2,
      // Décalage propre à chaque éclat, pour que le champ ne pulse pas
      // en bloc
      wobble: Math.random() * Math.PI * 2,
      offsetX: 0,
      offsetY: 0,
    };
  }

  /** Position et direction d'un éclat le long du flux choisi. */
  pathAt(shard, time) {
    const w = this.width;
    const h = this.height;
    const spread = this.options.spread;
    const flow = FLOWS[this.options.flow] ?? 0;

    if (flow === 1) {
      // Vortex : rotation autour du centre, les anneaux internes
      // tournent plus vite à vitesse tangentielle constante
      const radius = (0.12 + Math.sqrt(shard.phase) * 0.42)
        * Math.min(w, h) * spread;
      const angle = shard.phase * Math.PI * 2
        + (time * this.options.speed * 60) / Math.max(radius, 40);
      return {
        x: w / 2 + Math.cos(angle) * radius,
        y: h / 2 + Math.sin(angle) * radius * 0.75,
        dir: angle + Math.PI / 2,
      };
    }

    if (flow === 2) {
      // Ruban : une sinusoïde qui se replie sur elle-même
      const t = (shard.phase + time * 0.045 * this.options.speed) % 1;
      const x = t * (w + 200) - 100;
      const swing = Math.sin(t * Math.PI * 2) * h * 0.22 * spread;
      const fold = Math.cos(t * Math.PI * 4) * h * 0.08 * spread;
      return {
        x,
        y: h / 2 + swing + fold + shard.lane * h * 0.1 * spread,
        dir: Math.atan2(
          Math.cos(t * Math.PI * 2) * Math.PI * 2 * h * 0.22 / (w + 200),
          1),
      };
    }

    // Flux : diagonale douce traversant l'écran, la référence par défaut
    const t = (shard.phase + time * 0.03 * this.options.speed
               * (0.6 + shard.depth * 0.7)) % 1;
    const x = t * (w + 260) - 130;
    const drift = Math.sin(t * Math.PI * 1.7 + shard.wobble) * h * 0.26 * spread;
    return {
      x,
      y: h * 0.5 + drift + shard.lane * h * 0.2 * spread,
      dir: Math.atan2(
        Math.cos(t * Math.PI * 1.7 + shard.wobble) * Math.PI * 1.7 * h * 0.26,
        w + 260),
    };
  }

  /* ---------- interaction ---------- */

  addRipple(x, y) {
    // Ne jamais interrompre une onde en cours : des clics rapides
    // doivent s'ajouter, pas se remplacer
    if (this.ripples.length >= 4) this.ripples.shift();
    this.ripples.push({ x, y, age: 0 });
  }

  update(elapsed) {
    const mode = INTERACTIONS[this.options.interaction] ?? 1;
    const radius = 150 * this.options.interactionRadius;
    const strength = 90 * this.options.interactionStrength;

    for (const shard of this.shards) {
      shard.angle += shard.spin * this.options.spin * elapsed;

      // Retour élastique vers la position du flux : sans cela les éclats
      // repoussés ne reviendraient jamais
      shard.offsetX *= Math.exp(-2.4 * elapsed);
      shard.offsetY *= Math.exp(-2.4 * elapsed);

      if (mode !== 0 && this.pointer.active) {
        const px = shard.lastX ?? 0;
        const py = shard.lastY ?? 0;
        const dx = px - this.pointer.x;
        const dy = py - this.pointer.y;
        const distance = Math.hypot(dx, dy);
        if (distance < radius && distance > 0.001) {
          // Décroissance douce : pas de bord net autour du curseur
          const falloff = 1 - distance / radius;
          const push = falloff * falloff * strength * elapsed
            * (mode === 2 ? -1 : 1)
            // Les éclats proches réagissent plus que ceux du fond
            * (0.4 + shard.depth * 0.8);
          shard.offsetX += (dx / distance) * push;
          shard.offsetY += (dy / distance) * push;
        }
      }
    }

    for (const ripple of this.ripples) ripple.age += elapsed;
    this.ripples = this.ripples.filter((r) => r.age < RIPPLE_TAIL);
  }

  /* ---------- rendu ---------- */

  draw(time) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    const { r, g, b } = this.shardRgb;
    const accent = this.accentRgb;
    const baseOpacity = this.options.opacity;

    // Les éclats du fond d'abord : ceux de devant les recouvrent
    const ordered = [...this.shards].sort((a, c) => a.depth - c.depth);

    for (const shard of ordered) {
      const path = this.pathAt(shard, time);
      const x = path.x + shard.offsetX;
      const y = path.y + shard.offsetY;
      shard.lastX = x;
      shard.lastY = y;

      // Hors écran : rien à dessiner
      if (x < -80 || x > this.width + 80
          || y < -80 || y > this.height + 80) continue;

      // Une onde qui passe illumine l'éclat au moment précis où elle
      // l'atteint, comme une vague de lumière traversant le champ
      let pulse = 0;
      for (const ripple of this.ripples) {
        const distance = Math.hypot(x - ripple.x, y - ripple.y);
        const front = ripple.age * RIPPLE_SPEED;
        const delta = Math.abs(distance - front);
        if (delta < 90) {
          pulse = Math.max(pulse,
            (1 - delta / 90) * (1 - ripple.age / RIPPLE_TAIL)
            * this.options.rippleIntensity);
        }
      }

      const opacity = baseOpacity * (0.18 + shard.depth * 0.55);
      const length = shard.size * this.options.stretch;
      const width = shard.size * 0.34;

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(path.dir + shard.angle * 0.3);

      // Lueur : un halo tenu, jamais un flou d'image entière
      if (this.options.glow > 0) {
        ctx.shadowBlur = (7 + shard.depth * 13) * this.options.glow;
        ctx.shadowColor = pulse > 0.01
          ? `rgba(${accent.r},${accent.g},${accent.b},${0.5 * pulse})`
          : `rgba(${r},${g},${b},${opacity * 0.55})`;
      }

      // Losange allongé : deux triangles joints, comme l'éclat d'origine
      ctx.beginPath();
      ctx.moveTo(length * 0.5, 0);
      ctx.lineTo(0, -width);
      ctx.lineTo(-length * 0.5, 0);
      ctx.lineTo(0, width);
      ctx.closePath();

      if (pulse > 0.01) {
        const mix = Math.min(1, pulse);
        ctx.fillStyle = `rgba(${Math.round(r + (accent.r - r) * mix)},`
          + `${Math.round(g + (accent.g - g) * mix)},`
          + `${Math.round(b + (accent.b - b) * mix)},`
          + `${Math.min(0.95, opacity + pulse * 0.5)})`;
      } else {
        ctx.fillStyle = `rgba(${r},${g},${b},${opacity})`;
      }
      ctx.fill();
      ctx.restore();
    }
  }
}
