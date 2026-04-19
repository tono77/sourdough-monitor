// ─── Measurement detail + altura editor (unified modal) ───
//
// Clicking a chart point opens a big canvas modal: the same frame + green
// surface line used to label the ML training set, so corrections the user
// makes are immediately reusable as training data. On save, the measurement's
// altura_pct is overwritten with the corrected value and flagged as a manual
// override; the frame coordinates are persisted so a future retraining script
// can consume them the same way prepare_dataset.py consumes manual_labels.json.

const DEFAULT_FRAME = { tope: 20, base: 88, izq: 30, der: 70 };

// Module state
let _db = null;
let _doc = null;
let _updateDoc = null;
let _deleteDoc = null;
let _getSessionId = null;

let isOpen = false;
const state = {
  canvas: null,
  ctx: null,
  img: null,
  imgNatural: { w: 0, h: 0 },
  frame: { ...DEFAULT_FRAME },
  surf: 50,                 // image %
  view: { scale: 1, offsetX: 0, offsetY: 0 },
  dragging: null,           // "surf" | "f_tope" | "f_base" | "f_izq" | "f_der" | null
  panning: null,
  point: null,              // the measurement data from the chart point
};

// ─── public API ───────────────────────────────────────────────────────
export function initMeasurementDetail(db, docFn, updateDocFn, deleteDocFn, getSessionId) {
  _db = db;
  _doc = docFn;
  _updateDoc = updateDocFn;
  _deleteDoc = deleteDocFn;
  _getSessionId = getSessionId;
}

export function openMeasurementDetail(point) {
  if (!point || !point._id) return;
  const photoSrc = point.foto_url
    || (point.foto_drive_id ? `https://drive.google.com/uc?id=${point.foto_drive_id}` : null);
  if (!photoSrc) {
    alert("Esta medición no tiene foto.");
    return;
  }

  const modal = document.getElementById('measurementDetail');
  const canvas = document.getElementById('mdCanvas');
  if (!modal || !canvas) return;

  isOpen = true;
  state.point = point;
  state.canvas = canvas;
  state.ctx = canvas.getContext('2d');
  state.view = { scale: 1, offsetX: 0, offsetY: 0 };
  state.frame = { ...DEFAULT_FRAME };
  state.surf = 50;
  state.dragging = null;
  state.panning = null;

  populateHeader(point);
  populateFields(point);
  // Reset the save button in case a previous session left it in a stuck state.
  const saveBtn = document.getElementById('mdSaveBtn');
  if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Guardar corrección'; }
  const delBtn = document.getElementById('mdDeleteBtn');
  if (delBtn)  { delBtn.disabled  = false; delBtn.textContent  = 'Eliminar medición'; }
  wireEvents();

  // Preload session calibration (seed values for the frame), then the photo.
  fetchSessionCalibration().then(sessionCal => {
    const img = new Image();
    img.onload = () => {
      state.img = img;
      state.imgNatural = { w: img.naturalWidth, h: img.naturalHeight };
      // Two rAFs: ensure the grid layout has measured the body before we
      // size the canvas (single rAF is sometimes too early on Chromium).
      requestAnimationFrame(() => requestAnimationFrame(() => {
        fitCanvas();

        // Identity view: whole image fits the canvas, no zoom/pan on open.
        // User can zoom in with the wheel if they need precision.
        state.view = { scale: 1, offsetX: 0, offsetY: 0 };

        // Frame position (canvas %, which equals image % at identity view):
        // 1) previous manual correction on this measurement
        // 2) session calibration
        // 3) defaults
        if (typeof point.manual_tope_y_pct === 'number') {
          state.frame = {
            tope: point.manual_tope_y_pct, base: point.manual_base_y_pct,
            izq:  point.manual_izq_x_pct,  der:  point.manual_der_x_pct,
          };
          state.surf = point.manual_surface_y_pct;
        } else if (sessionCal && sessionCal.tope != null && sessionCal.izq != null) {
          state.frame = {
            tope: sessionCal.tope, base: sessionCal.base,
            izq:  sessionCal.izq,  der:  sessionCal.der,
          };
          const alt = (typeof point.altura_pct === 'number') ? point.altura_pct : 50;
          state.surf = state.frame.base - (alt / 100) * (state.frame.base - state.frame.tope);
        } else {
          state.frame = { ...DEFAULT_FRAME };
          const alt = (typeof point.altura_pct === 'number') ? point.altura_pct : 50;
          state.surf = state.frame.base - (alt / 100) * (state.frame.base - state.frame.tope);
        }
        render();
      }));
    };
    img.onerror = () => {
      alert("No se pudo cargar la foto.");
      closeMeasurementDetail();
    };
    img.src = photoSrc;
  });

  modal.classList.add('open');
}

export function closeMeasurementDetail() {
  const modal = document.getElementById('measurementDetail');
  if (modal) modal.classList.remove('open');
  unwireEvents();
  isOpen = false;
  state.img = null;
  state.point = null;
}

/** Delete the current measurement. Wired to the modal's delete button. */
export async function deleteMeasurement() {
  const m = state.point;
  const sid = _getSessionId();
  if (!m || !m._id || !sid || !_db) { alert("No se pudo identificar la medición."); return; }
  if (!confirm("¿Eliminar esta medición? Esta acción no se puede deshacer.")) return;

  const btn = document.getElementById('mdDeleteBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Eliminando…'; }
  try {
    await _deleteDoc(_doc(_db, 'sesiones', sid, 'mediciones', m._id));
    closeMeasurementDetail();
  } catch (e) {
    alert("Error al eliminar: " + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Eliminar medición'; }
  }
}

/** Save altura correction + auxiliary field edits (burbujas, textura). */
export async function saveMeasurementDetail() {
  const m = state.point;
  const sid = _getSessionId();
  if (!m || !m._id || !sid || !_db) { alert("No se pudo identificar la medición."); return; }

  const f = frameToImgPct();
  const correctedAltura = computeAltura();
  const burbujas = document.getElementById('mdBurbujas').value;
  const textura  = document.getElementById('mdTextura').value;

  const btn = document.getElementById('mdSaveBtn');
  const resetBtn = () => {
    if (btn) { btn.disabled = false; btn.textContent = 'Guardar corrección'; }
  };
  if (btn) { btn.disabled = true; btn.textContent = 'Guardando…'; }

  // Fail-loud timeout so the UI never gets stuck if Firestore hangs.
  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("timeout después de 10s")), 10000));

  try {
    const payload = {
      altura_pct: Math.round(correctedAltura * 10) / 10,
      burbujas, textura,
      is_manual_override: true,
      manual_tope_y_pct:    f.tope,
      manual_base_y_pct:    f.base,
      manual_izq_x_pct:     f.izq,
      manual_der_x_pct:     f.der,
      manual_surface_y_pct: state.surf,
      manual_corrected_at:  new Date().toISOString(),
    };
    console.log('[md] saving to', `sesiones/${sid}/mediciones/${m._id}`, payload);
    await Promise.race([
      _updateDoc(_doc(_db, 'sesiones', sid, 'mediciones', m._id), payload),
      timeout,
    ]);
    console.log('[md] save OK');
    closeMeasurementDetail();
  } catch (e) {
    console.error('[md] save error:', e);
    alert("Error al guardar: " + (e.message || e));
    resetBtn();
  }
}

// ─── panel/header population ──────────────────────────────────────────
function populateHeader(m) {
  const ts = m.timestamp ? new Date(m.timestamp) : null;
  const tsStr = ts ? ts.toLocaleString('es', {
    day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }) : '';
  const el = document.getElementById('mdTimestamp');
  if (el) el.textContent = tsStr;
}

function populateFields(m) {
  const fused = m.altura_pct;
  const ml    = m.ml_altura_pct;
  document.getElementById('mdAlturaFused').textContent =
    (typeof fused === 'number') ? `${fused.toFixed(1)}%` : '—';
  document.getElementById('mdAlturaMl').textContent =
    (typeof ml === 'number') ? `${ml.toFixed(1)}%` : '—';

  document.getElementById('mdBurbujas').value = m.burbujas || 'ninguna';
  document.getElementById('mdTextura').value  = m.textura  || 'lisa';
}

async function fetchSessionCalibration() {
  const sid = _getSessionId();
  if (!sid) return null;
  try {
    const { getDoc } = await import('https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js');
    const snap = await getDoc(_doc(_db, 'sesiones', sid));
    if (!snap.exists()) return null;
    const d = snap.data();
    if (!d.is_calibrated) return null;
    return { tope: d.tope_y_pct, base: d.base_y_pct, izq: d.izq_x_pct, der: d.der_x_pct };
  } catch (e) {
    console.warn("Could not fetch session calibration:", e);
    return null;
  }
}

// ─── rendering ────────────────────────────────────────────────────────
function fitCanvas() {
  if (!state.imgNatural.w) return;
  const body = state.canvas.parentElement;
  // Body is a flex container with 16px padding; subtract it so the canvas
  // fits INSIDE the padding box (not outside it, which caused overflow on
  // tight layouts and clipped the BASE frame line).
  const rect = body.getBoundingClientRect();
  const padX = 32;  // 16px left + 16px right
  const padY = 32;
  const maxW = Math.max(200, rect.width  - padX);
  const maxH = Math.max(200, rect.height - padY);
  const r = state.imgNatural.w / state.imgNatural.h;
  let w = maxW, h = w / r;
  if (h > maxH) { h = maxH; w = h * r; }
  state.canvas.width  = Math.floor(w);
  state.canvas.height = Math.floor(h);
  render();
}

function imgPctToCanvas(px, py) {
  const v = state.view;
  return {
    x: v.offsetX + (px / 100) * state.canvas.width  * v.scale,
    y: v.offsetY + (py / 100) * state.canvas.height * v.scale,
  };
}
function canvasToImgPct(cx, cy) {
  const v = state.view;
  return {
    x: ((cx - v.offsetX) / (state.canvas.width  * v.scale)) * 100,
    y: ((cy - v.offsetY) / (state.canvas.height * v.scale)) * 100,
  };
}
function frameToImgPct() {
  const ch = state.canvas.height, cw = state.canvas.width;
  return {
    tope: canvasToImgPct(0, state.frame.tope / 100 * ch).y,
    base: canvasToImgPct(0, state.frame.base / 100 * ch).y,
    izq:  canvasToImgPct(state.frame.izq / 100 * cw, 0).x,
    der:  canvasToImgPct(state.frame.der / 100 * cw, 0).x,
  };
}
function computeAltura() {
  const f = frameToImgPct();
  if (f.base <= f.tope) return 0;
  return Math.max(0, Math.min(100, (f.base - state.surf) / (f.base - f.tope) * 100));
}

function render() {
  const ctx = state.ctx, c = state.canvas;
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, c.width, c.height);
  if (!state.img) return;

  const v = state.view;
  ctx.drawImage(state.img, v.offsetX, v.offsetY, c.width * v.scale, c.height * v.scale);

  const cw = c.width, ch = c.height;
  const topeY = state.frame.tope / 100 * ch;
  const baseY = state.frame.base / 100 * ch;
  const izqX  = state.frame.izq  / 100 * cw;
  const derX  = state.frame.der  / 100 * cw;

  ctx.strokeStyle = 'rgba(255, 80, 80, 0.85)';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  drawHLine(topeY, 'TOPE');
  drawHLine(baseY, 'BASE');
  drawVLine(izqX,  'IZQ');
  drawVLine(derX,  'DER');

  ctx.setLineDash([]);
  ctx.strokeStyle = 'rgba(74, 222, 128, 0.95)';
  ctx.lineWidth = 3;
  const sy = imgPctToCanvas(0, state.surf).y;
  ctx.beginPath();
  ctx.moveTo(izqX, sy); ctx.lineTo(derX, sy);
  ctx.stroke();
  ctx.fillStyle = '#4ade80';
  drawHandle(izqX, sy);
  drawHandle(derX, sy);
  ctx.font = 'bold 13px sans-serif';
  ctx.fillText(`SUPERFICIE ${computeAltura().toFixed(1)}%`, izqX + 6, sy - 6);

  const out = document.getElementById('mdAlturaCorrected');
  if (out) out.textContent = computeAltura().toFixed(1);
}
function drawHLine(y, label) {
  const ctx = state.ctx, c = state.canvas;
  ctx.beginPath();
  ctx.moveTo(0, y); ctx.lineTo(c.width, y);
  ctx.stroke();
  ctx.save();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(255,80,80,0.95)';
  ctx.font = '11px sans-serif';
  ctx.fillText(label, 4, y - 4);
  ctx.restore();
}
function drawVLine(x, label) {
  const ctx = state.ctx, c = state.canvas;
  ctx.beginPath();
  ctx.moveTo(x, 0); ctx.lineTo(x, c.height);
  ctx.stroke();
  ctx.save();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(255,80,80,0.95)';
  ctx.font = '11px sans-serif';
  ctx.fillText(label, x + 4, 12);
  ctx.restore();
}
function drawHandle(x, y) {
  const ctx = state.ctx;
  ctx.beginPath();
  ctx.arc(x, y, 6, 0, Math.PI * 2);
  ctx.fill();
}

// ─── interaction ──────────────────────────────────────────────────────
const HIT_THRESH = 12;
function getMousePos(e) {
  const r = state.canvas.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}
function hitTest(x, y) {
  const cw = state.canvas.width, ch = state.canvas.height;
  const f = state.frame;
  const topeY = f.tope / 100 * ch;
  const baseY = f.base / 100 * ch;
  const izqX  = f.izq  / 100 * cw;
  const derX  = f.der  / 100 * cw;
  const surfY = imgPctToCanvas(0, state.surf).y;
  if (x >= izqX - 24 && x <= derX + 24 && Math.abs(surfY - y) < HIT_THRESH) return 'surf';
  if (Math.abs(topeY - y) < HIT_THRESH) return 'f_tope';
  if (Math.abs(baseY - y) < HIT_THRESH) return 'f_base';
  if (Math.abs(izqX  - x) < HIT_THRESH) return 'f_izq';
  if (Math.abs(derX  - x) < HIT_THRESH) return 'f_der';
  return null;
}
function cursorFor(hit) {
  if (hit === 'surf' || hit === 'f_tope' || hit === 'f_base') return 'ns-resize';
  if (hit === 'f_izq' || hit === 'f_der') return 'ew-resize';
  return 'grab';
}
function onMouseDown(e) {
  const { x, y } = getMousePos(e);
  const forcePan = e.altKey || e.shiftKey || e.button === 1;
  const hit = forcePan ? null : hitTest(x, y);
  if (hit) state.dragging = hit;
  else state.panning = { lastX: x, lastY: y };
  state.canvas.style.cursor = 'grabbing';
  e.preventDefault();
}
function onMouseMove(e) {
  const { x, y } = getMousePos(e);
  if (state.panning) {
    state.view.offsetX += x - state.panning.lastX;
    state.view.offsetY += y - state.panning.lastY;
    state.panning.lastX = x; state.panning.lastY = y;
    render();
    return;
  }
  if (state.dragging) {
    const cw = state.canvas.width, ch = state.canvas.height;
    const d = state.dragging;
    if (d === 'surf') {
      state.surf = Math.max(0, Math.min(100, canvasToImgPct(x, y).y));
    } else if (d === 'f_tope' || d === 'f_base') {
      state.frame[d.slice(2)] = Math.max(0, Math.min(100, y / ch * 100));
    } else if (d === 'f_izq' || d === 'f_der') {
      state.frame[d.slice(2)] = Math.max(0, Math.min(100, x / cw * 100));
    }
    render();
    return;
  }
  state.canvas.style.cursor = cursorFor(hitTest(x, y));
}
function onMouseUp() {
  state.dragging = null;
  state.panning = null;
  if (state.canvas) state.canvas.style.cursor = 'crosshair';
}
function onWheel(e) {
  e.preventDefault();
  const { x, y } = getMousePos(e);
  const old = state.view.scale;
  const factor = e.deltaY > 0 ? (1 / 1.15) : 1.15;
  const next = Math.max(0.5, Math.min(10, old * factor));
  if (next === old) return;
  state.view.offsetX = x - (x - state.view.offsetX) * (next / old);
  state.view.offsetY = y - (y - state.view.offsetY) * (next / old);
  state.view.scale = next;
  render();
}
function onKey(e) {
  if (!isOpen) return;
  if (e.key === 'Escape') closeMeasurementDetail();
  else if (e.key === 'Enter') saveMeasurementDetail();
  else if (e.key === '0') {
    state.view = { scale: 1, offsetX: 0, offsetY: 0 };
    render();
  }
}
function onResize() { fitCanvas(); }

function wireEvents() {
  const c = state.canvas;
  c.addEventListener('mousedown', onMouseDown);
  c.addEventListener('mousemove', onMouseMove);
  c.addEventListener('mouseup',   onMouseUp);
  c.addEventListener('mouseleave', onMouseUp);
  c.addEventListener('wheel', onWheel, { passive: false });
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', onResize);
}
function unwireEvents() {
  const c = state.canvas;
  if (!c) return;
  c.removeEventListener('mousedown', onMouseDown);
  c.removeEventListener('mousemove', onMouseMove);
  c.removeEventListener('mouseup',   onMouseUp);
  c.removeEventListener('mouseleave', onMouseUp);
  c.removeEventListener('wheel', onWheel);
  document.removeEventListener('keydown', onKey);
  window.removeEventListener('resize', onResize);
}
