// Shared jar-frame component.
// Renders an image with 4 corner handles (defining TOPE/BASE/IZQ/DER of the
// jar), a rectangle between them, a draggable green surface line (masa level),
// and top/bottom labels. Used by mobile calibrate and desktop measurement
// correction flows.

const DEFAULT_FRAME = { tope: 20, base: 88, izq: 30, der: 70 };
const MIN_FRAME_GAP = 5;

export function createJarFrame(container, opts = {}) {
  const onChange = opts.onChange || (() => {});

  container.classList.add('jar-frame');
  container.innerHTML = `
    <img class="jar-frame-img" alt="Medición" draggable="false">
    <div class="jar-frame-rect" data-rect></div>
    <div class="jar-frame-label" data-at="top" data-label-top>TOPE 100%</div>
    <div class="jar-frame-label" data-at="bottom" data-label-bottom>FONDO 0%</div>
    <div class="jar-frame-handle" data-corner="tl" aria-label="Esquina superior izquierda"></div>
    <div class="jar-frame-handle" data-corner="tr" aria-label="Esquina superior derecha"></div>
    <div class="jar-frame-handle" data-corner="bl" aria-label="Esquina inferior izquierda"></div>
    <div class="jar-frame-handle" data-corner="br" aria-label="Esquina inferior derecha"></div>
    <div class="jar-frame-surface" data-surface aria-label="Nivel de la masa"></div>
  `;

  const state = {
    frame: { ...DEFAULT_FRAME },
    surface: 50,
    dragging: null,
  };

  const $img = container.querySelector('.jar-frame-img');
  const $rect = container.querySelector('[data-rect]');
  const $labelTop = container.querySelector('[data-label-top]');
  const $labelBot = container.querySelector('[data-label-bottom]');
  const $handles = container.querySelectorAll('.jar-frame-handle');
  const $surface = container.querySelector('[data-surface]');

  $img.addEventListener('load', () => {
    if ($img.naturalWidth && $img.naturalHeight) {
      container.style.aspectRatio = `${$img.naturalWidth} / ${$img.naturalHeight}`;
    }
  });

  function emit() {
    onChange({ frame: { ...state.frame }, surface: state.surface, altura: computeAltura() });
  }

  function computeAltura() {
    const span = state.frame.base - state.frame.tope;
    if (span <= 0) return 0;
    return clamp(((state.frame.base - state.surface) / span) * 100, 0, 150);
  }

  function render() {
    positionHandles();
    positionRect();
    positionSurface();
    positionLabels();
  }

  function positionHandles() {
    const map = {
      tl: [state.frame.izq, state.frame.tope],
      tr: [state.frame.der, state.frame.tope],
      bl: [state.frame.izq, state.frame.base],
      br: [state.frame.der, state.frame.base],
    };
    $handles.forEach(h => {
      const [x, y] = map[h.dataset.corner];
      h.style.left = `${x}%`;
      h.style.top = `${y}%`;
    });
  }

  function positionRect() {
    $rect.style.left = `${state.frame.izq}%`;
    $rect.style.top = `${state.frame.tope}%`;
    $rect.style.width = `${Math.max(0, state.frame.der - state.frame.izq)}%`;
    $rect.style.height = `${Math.max(0, state.frame.base - state.frame.tope)}%`;
  }

  function positionSurface() {
    $surface.style.top = `${state.surface}%`;
    $surface.style.left = `${state.frame.izq}%`;
    $surface.style.width = `${Math.max(0, state.frame.der - state.frame.izq)}%`;
  }

  function positionLabels() {
    $labelTop.style.top = `${state.frame.tope}%`;
    $labelTop.style.left = `${(state.frame.izq + state.frame.der) / 2}%`;
    $labelBot.style.top = `${state.frame.base}%`;
    $labelBot.style.left = `${(state.frame.izq + state.frame.der) / 2}%`;
  }

  // ── Pointer events (unified mouse + touch) ──────────────────────────
  const onPointerDown = (e, target) => {
    e.preventDefault();
    state.dragging = target;
    container.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e) => {
    if (!state.dragging) return;
    const rect = container.getBoundingClientRect();
    const x = clamp(e.clientX - rect.left, 0, rect.width);
    const y = clamp(e.clientY - rect.top, 0, rect.height);
    const xp = (x / rect.width) * 100;
    const yp = (y / rect.height) * 100;

    const d = state.dragging;
    if (d === 'surface') {
      state.surface = clamp(yp, Math.min(state.frame.tope, state.frame.base), Math.max(state.frame.tope, state.frame.base));
    } else {
      if (d.includes('t')) state.frame.tope = Math.min(yp, state.frame.base - MIN_FRAME_GAP);
      if (d.includes('b')) state.frame.base = Math.max(yp, state.frame.tope + MIN_FRAME_GAP);
      if (d.includes('l')) state.frame.izq = Math.min(xp, state.frame.der - MIN_FRAME_GAP);
      if (d.includes('r')) state.frame.der = Math.max(xp, state.frame.izq + MIN_FRAME_GAP);
      state.surface = clamp(state.surface, state.frame.tope, state.frame.base);
    }
    render();
    emit();
  };

  const onPointerUp = (e) => {
    if (state.dragging && container.hasPointerCapture(e.pointerId)) {
      container.releasePointerCapture(e.pointerId);
    }
    state.dragging = null;
  };

  $handles.forEach(h => {
    h.addEventListener('pointerdown', (e) => onPointerDown(e, h.dataset.corner));
  });
  $surface.addEventListener('pointerdown', (e) => onPointerDown(e, 'surface'));
  container.addEventListener('pointermove', onPointerMove);
  container.addEventListener('pointerup', onPointerUp);
  container.addEventListener('pointercancel', onPointerUp);

  render();

  return {
    setImage(src) {
      if (!src) { $img.removeAttribute('src'); return; }
      if ($img.getAttribute('src') !== src) $img.src = src;
    },
    setFrame(frame) {
      state.frame = { ...frame };
      state.surface = clamp(state.surface, state.frame.tope, state.frame.base);
      render();
    },
    setSurface(surface) {
      state.surface = clamp(surface, state.frame.tope, state.frame.base);
      render();
    },
    setSurfaceFromAltura(altura) {
      const span = state.frame.base - state.frame.tope;
      state.surface = clamp(state.frame.base - (altura / 100) * span, state.frame.tope, state.frame.base);
      render();
    },
    getState() {
      return { frame: { ...state.frame }, surface: state.surface, altura: computeAltura() };
    },
    destroy() {
      container.removeEventListener('pointermove', onPointerMove);
      container.removeEventListener('pointerup', onPointerUp);
      container.removeEventListener('pointercancel', onPointerUp);
      container.classList.remove('jar-frame');
      container.innerHTML = '';
    },
  };
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
