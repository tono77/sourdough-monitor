import { createJarFrame } from '../shared/jar-frame.js';

const DEFAULT_FRAME = { tope: 20, base: 88, izq: 30, der: 70 };
const DEFAULT_SURFACE = 50;

let root = null;
let ctx = null;
let jar = null;

export function openCalibrate(opts) {
  root = document.getElementById('mCalibrate');
  ctx = { ...opts, idx: 0, burbujas: null, textura: null, saving: false };
  root.innerHTML = buildMarkup(ctx);
  root.hidden = false;

  const photoHost = root.querySelector('[data-photo]');
  jar = createJarFrame(photoHost, {
    onChange: ({ altura }) => {
      const slider = root.querySelector('[data-slider]');
      const pctEl = root.querySelector('[data-pct]');
      const rounded = Math.round(altura);
      slider.value = String(Math.max(0, Math.min(150, rounded)));
      pctEl.textContent = `${rounded}%`;
    },
  });

  wire(ctx);
  loadMeasurement(ctx, 0);
}

function close() {
  if (!root) return;
  if (jar) { jar.destroy(); jar = null; }
  root.hidden = true;
  root.innerHTML = '';
  ctx = null;
  root = null;
}

function buildMarkup({ queue }) {
  const chips = queue.map((m, i) => {
    const t = fmtTime(m.timestamp);
    const pct = pickPct(m);
    return `<button class="m-cal-chip" data-idx="${i}" type="button">${t} · ${pct != null ? Math.round(pct) : '—'}%</button>`;
  }).join('');

  return `
    <div class="m-cal-header">
      <button class="m-cal-close" data-act="close" type="button">← CERRAR</button>
      <span class="m-cal-title">CALIBRAR <span data-cur>1</span>/<span data-total>${queue.length}</span></span>
      <span class="m-cal-stamp" data-stamp>—</span>
    </div>
    <div class="m-cal-queue" role="tablist">${chips}</div>
    <div class="m-cal-body">
      <div class="m-cal-photo-wrap" data-photo></div>
      <div class="m-cal-instruct">ARRASTRA LAS ESQUINAS · MARCA FONDO Y TOPE DEL FRASCO</div>
      <div class="m-cal-field">
        <div class="m-cal-field-head">
          <span>CRECIMIENTO %</span>
          <span class="m-cal-field-value" data-pct>—%</span>
        </div>
        <input class="m-cal-slider" type="range" min="0" max="150" step="1" data-slider aria-label="Crecimiento por ciento">
        <div class="m-cal-scale"><span>0</span><span>50</span><span>100</span><span>150</span></div>
      </div>
      <div class="m-cal-field">
        <div class="m-cal-field-head"><span>BURBUJAS</span></div>
        <div class="m-cal-chips" data-bubs>
          <button type="button" data-val="ninguna">NINGUNA</button>
          <button type="button" data-val="pocas">POCAS</button>
          <button type="button" data-val="muchas">MUCHAS</button>
        </div>
      </div>
      <div class="m-cal-field">
        <div class="m-cal-field-head"><span>TEXTURA</span></div>
        <div class="m-cal-chips" data-texs>
          <button type="button" data-val="lisa">LISA</button>
          <button type="button" data-val="rugosa">RUGOSA</button>
          <button type="button" data-val="muy_activa">MUY ACTIVA</button>
        </div>
      </div>
    </div>
    <div class="m-cal-actions">
      <button class="m-cal-btn m-cal-btn-secondary" data-act="skip" type="button">OMITIR</button>
      <button class="m-cal-btn m-cal-btn-primary" data-act="save" type="button">GUARDAR · SIGUIENTE →</button>
    </div>
  `;
}

function wire(c) {
  root.querySelectorAll('[data-act]').forEach(btn => {
    btn.onclick = () => {
      const a = btn.dataset.act;
      if (a === 'close') close();
      else if (a === 'save') saveAndNext(c);
      else if (a === 'skip') skip(c);
    };
  });

  root.querySelectorAll('.m-cal-chip').forEach(chip => {
    chip.onclick = () => loadMeasurement(c, Number(chip.dataset.idx));
  });

  root.querySelector('[data-slider]').oninput = (e) => {
    jar.setSurfaceFromAltura(Number(e.target.value));
    const pctEl = root.querySelector('[data-pct]');
    pctEl.textContent = `${Math.round(jar.getState().altura)}%`;
  };

  root.querySelector('[data-bubs]').onclick = (e) => {
    const b = e.target.closest('button[data-val]');
    if (!b) return;
    c.burbujas = b.dataset.val;
    setChipActive(root.querySelector('[data-bubs]'), c.burbujas);
  };
  root.querySelector('[data-texs]').onclick = (e) => {
    const b = e.target.closest('button[data-val]');
    if (!b) return;
    c.textura = b.dataset.val;
    setChipActive(root.querySelector('[data-texs]'), c.textura);
  };
}

function setChipActive(group, val) {
  group.querySelectorAll('button').forEach(b => {
    b.setAttribute('aria-pressed', b.dataset.val === val ? 'true' : 'false');
  });
}

function loadMeasurement(c, idx) {
  if (idx < 0 || idx >= c.queue.length) return;
  c.idx = idx;
  const m = c.queue[idx];

  let frame, surface;
  if (typeof m.manual_tope_y_pct === 'number') {
    frame = {
      tope: m.manual_tope_y_pct, base: m.manual_base_y_pct,
      izq: m.manual_izq_x_pct, der: m.manual_der_x_pct,
    };
    surface = m.manual_surface_y_pct ?? DEFAULT_SURFACE;
  } else if (c.session && typeof c.session.tope_y_pct === 'number') {
    frame = {
      tope: c.session.tope_y_pct, base: c.session.base_y_pct,
      izq: c.session.izq_x_pct, der: c.session.der_x_pct,
    };
    const span = frame.base - frame.tope;
    const alt = pickPct(m) ?? DEFAULT_SURFACE;
    surface = frame.base - (alt / 100) * span;
  } else {
    frame = { ...DEFAULT_FRAME };
    const span = frame.base - frame.tope;
    const alt = pickPct(m) ?? DEFAULT_SURFACE;
    surface = frame.base - (alt / 100) * span;
  }
  c.burbujas = m.burbujas || null;
  c.textura = m.textura || null;

  root.querySelector('[data-cur]').textContent = String(idx + 1);
  root.querySelector('[data-total]').textContent = String(c.queue.length);
  root.querySelector('[data-stamp]').textContent = fmtTime(m.timestamp);

  root.querySelectorAll('.m-cal-chip').forEach((chip, i) => {
    chip.setAttribute('aria-pressed', i === idx ? 'true' : 'false');
  });

  const src = m.foto_url || (m.foto_drive_id ? `https://drive.google.com/uc?id=${m.foto_drive_id}` : null);
  jar.setImage(src);
  jar.setFrame(frame);
  jar.setSurface(surface);

  setChipActive(root.querySelector('[data-bubs]'), c.burbujas);
  setChipActive(root.querySelector('[data-texs]'), c.textura);

  const { altura } = jar.getState();
  const rounded = Math.round(altura);
  root.querySelector('[data-slider]').value = String(Math.max(0, Math.min(150, rounded)));
  root.querySelector('[data-pct]').textContent = `${rounded}%`;
}

async function saveAndNext(c) {
  if (c.saving) return;
  c.saving = true;
  const btn = root.querySelector('[data-act="save"]');
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'GUARDANDO…';

  const m = c.queue[c.idx];
  const { frame, surface, altura } = jar.getState();
  const payload = {
    altura_pct: Math.round(altura * 10) / 10,
    burbujas: c.burbujas || (m.burbujas || 'ninguna'),
    textura: c.textura || (m.textura || 'lisa'),
    is_manual_override: true,
    manual_tope_y_pct: frame.tope,
    manual_base_y_pct: frame.base,
    manual_izq_x_pct: frame.izq,
    manual_der_x_pct: frame.der,
    manual_surface_y_pct: surface,
    manual_corrected_at: new Date().toISOString(),
  };

  try {
    await c.updateDoc(c.doc(c.db, 'sesiones', c.sessionId, 'mediciones', m._id), payload);
    if (typeof c.onSaved === 'function') c.onSaved();
    if (navigator.vibrate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      navigator.vibrate(15);
    }
    if (c.idx < c.queue.length - 1) {
      c.saving = false;
      btn.disabled = false;
      btn.textContent = originalText;
      loadMeasurement(c, c.idx + 1);
    } else {
      close();
    }
  } catch (e) {
    c.saving = false;
    btn.disabled = false;
    btn.textContent = originalText;
    alert('Error al guardar: ' + (e.message || e));
  }
}

function skip(c) {
  if (c.idx < c.queue.length - 1) loadMeasurement(c, c.idx + 1);
  else close();
}

function pickPct(m) {
  if (!m) return null;
  if (m.altura_pct != null) return parseFloat(m.altura_pct);
  if (m.nivel_pct != null) return parseFloat(m.nivel_pct);
  return null;
}

function fmtTime(iso) {
  if (!iso) return '--:--';
  return new Date(iso).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
}
