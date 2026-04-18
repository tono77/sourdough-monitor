// ─── Calibration: frame-based canvas UI ───
//
// Replaces the old 5-click flow with a draggable red rectangle + orange band
// line on top of a pan/zoom-able photo. The user aligns the frame to the
// jar (drag lines OR pan the image) and positions the band line on the red
// elastic. Saving projects all 5 lines to image % and writes them to the
// session document in Firestore.

// Default positions (CANVAS percentages). Tuned to roughly match the average
// jar framing; the user tweaks per-session as needed.
const DEFAULT_FRAME = { tope: 20, base: 88, izq: 30, der: 70 };
const DEFAULT_BANDA = 65;  // band line Y (canvas %)

// Module state
let _db = null;
let _doc = null;
let _updateDoc = null;
let _getCurrentSessionId = null;
let _getAllMeasurements = null;
let _onComplete = null;  // optional callback after successful save

let isCalibrating = false;

// Canvas state (kept module-local so render/interaction handlers can read it)
const cal = {
  canvas: null,
  ctx: null,
  img: null,
  imgNatural: { w: 0, h: 0 },
  frame: { ...DEFAULT_FRAME },
  banda: DEFAULT_BANDA,
  view: { scale: 1, offsetX: 0, offsetY: 0 },
  dragging: null,   // "f_tope" | "f_base" | "f_izq" | "f_der" | "banda" | null
  panning: null,
};

// ─── public API ────────────────────────────────────────────────────────
export function initCalibration(db, docFn, updateDocFn, getCurrentSessionId, getAllMeasurements) {
  _db = db;
  _doc = docFn;
  _updateDoc = updateDocFn;
  _getCurrentSessionId = getCurrentSessionId;
  _getAllMeasurements = getAllMeasurements;
}

export function getIsCalibrating() {
  return isCalibrating;
}

/**
 * Open the calibration modal. Optional `onComplete` callback fires after
 * a successful save (used by the new-cycle flow to follow up with a toast).
 */
export async function startCalibration(onComplete) {
  const sessionId = _getCurrentSessionId();
  if (!sessionId) {
    alert("No hay sesión activa.");
    return;
  }
  const photoSrc = pickCalibrationPhotoSrc();
  if (!photoSrc) {
    alert("No hay fotos disponibles para calibrar.");
    return;
  }
  _onComplete = typeof onComplete === "function" ? onComplete : null;

  const existing = await fetchExistingCalibration(sessionId);
  openModal(photoSrc, existing);
}

// ─── photo + Firestore helpers ─────────────────────────────────────────
function pickCalibrationPhotoSrc() {
  const meds = _getAllMeasurements ? _getAllMeasurements() : [];
  // Newest-first preference: the most recent measurement with a photo.
  for (let i = meds.length - 1; i >= 0; i--) {
    const m = meds[i];
    if (m && m.foto_url) return m.foto_url;
    if (m && m.foto_drive_id) return `https://drive.google.com/uc?id=${m.foto_drive_id}`;
  }
  return null;
}

async function fetchExistingCalibration(sessionId) {
  try {
    const { getDoc } = await import('https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js');
    const snap = await getDoc(_doc(_db, 'sesiones', sessionId));
    if (!snap.exists()) return null;
    const d = snap.data();
    if (!d.is_calibrated) return null;
    return {
      tope_y_pct: d.tope_y_pct,
      base_y_pct: d.base_y_pct,
      izq_x_pct:  d.izq_x_pct,
      der_x_pct:  d.der_x_pct,
      fondo_y_pct: d.fondo_y_pct,
    };
  } catch (e) {
    console.warn("Could not fetch existing calibration:", e);
    return null;
  }
}

// ─── modal open/close ──────────────────────────────────────────────────
function openModal(photoSrc, existing) {
  isCalibrating = true;
  const modal = document.getElementById('calibModal');
  const canvas = document.getElementById('calibCanvas');
  if (!modal || !canvas) {
    console.error("Calibration modal not found in DOM");
    isCalibrating = false;
    return;
  }
  modal.style.display = 'flex';
  cal.canvas = canvas;
  cal.ctx = canvas.getContext('2d');

  // Reset transient state; keep frame at defaults unless existing calibration.
  cal.view = { scale: 1, offsetX: 0, offsetY: 0 };
  cal.frame = { ...DEFAULT_FRAME };
  cal.banda = DEFAULT_BANDA;
  cal.dragging = null;
  cal.panning = null;

  wireEvents();

  const img = new Image();
  img.onload = () => {
    cal.img = img;
    cal.imgNatural = { w: img.naturalWidth, h: img.naturalHeight };
    fitCanvas();
    // If existing calibration: keep view at identity, frame = saved image-% values
    // (they equal canvas % at identity view, so the user sees the jar already
    // framed where it was last calibrated).
    if (existing && existing.tope_y_pct != null) {
      cal.frame.tope = existing.tope_y_pct;
      cal.frame.base = existing.base_y_pct;
      cal.frame.izq  = existing.izq_x_pct;
      cal.frame.der  = existing.der_x_pct;
      if (existing.fondo_y_pct != null) cal.banda = existing.fondo_y_pct;
    }
    render();
  };
  img.onerror = () => {
    alert("No se pudo cargar la foto para calibrar.");
    closeModal();
  };
  img.src = photoSrc;
}

function closeModal() {
  const modal = document.getElementById('calibModal');
  if (modal) modal.style.display = 'none';
  unwireEvents();
  isCalibrating = false;
  cal.img = null;
  _onComplete = null;
}

async function saveCalibration() {
  const sessionId = _getCurrentSessionId();
  if (!sessionId) { alert("Sin sesión activa."); return; }
  const f = frameToImgPct();
  const banda = canvasToImgPct(0, cal.banda / 100 * cal.canvas.height).y;
  try {
    await _updateDoc(_doc(_db, 'sesiones', sessionId), {
      tope_y_pct:  f.tope,
      base_y_pct:  f.base,
      izq_x_pct:   f.izq,
      der_x_pct:   f.der,
      fondo_y_pct: banda,
      is_calibrated: 1,
    });
    const cb = _onComplete;
    closeModal();
    if (cb) cb();
  } catch (e) {
    alert("Error guardando calibración: " + e.message);
  }
}

// ─── rendering ─────────────────────────────────────────────────────────
function fitCanvas() {
  const body = cal.canvas.parentElement;
  const maxW = body.clientWidth;
  const maxH = body.clientHeight;
  if (!cal.imgNatural.w) return;
  const r = cal.imgNatural.w / cal.imgNatural.h;
  let w = maxW, h = w / r;
  if (h > maxH) { h = maxH; w = h * r; }
  cal.canvas.width  = Math.floor(w);
  cal.canvas.height = Math.floor(h);
  render();
}

function imgPctToCanvas(px_pct, py_pct) {
  const v = cal.view;
  return {
    x: v.offsetX + (px_pct / 100) * cal.canvas.width  * v.scale,
    y: v.offsetY + (py_pct / 100) * cal.canvas.height * v.scale,
  };
}
function canvasToImgPct(cx, cy) {
  const v = cal.view;
  return {
    x: ((cx - v.offsetX) / (cal.canvas.width  * v.scale)) * 100,
    y: ((cy - v.offsetY) / (cal.canvas.height * v.scale)) * 100,
  };
}

function frameToImgPct() {
  const ch = cal.canvas.height, cw = cal.canvas.width;
  return {
    tope: canvasToImgPct(0, cal.frame.tope / 100 * ch).y,
    base: canvasToImgPct(0, cal.frame.base / 100 * ch).y,
    izq:  canvasToImgPct(cal.frame.izq / 100 * cw, 0).x,
    der:  canvasToImgPct(cal.frame.der / 100 * cw, 0).x,
  };
}

function render() {
  const ctx = cal.ctx, c = cal.canvas;
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, c.width, c.height);
  if (!cal.img) return;

  const v = cal.view;
  ctx.drawImage(cal.img, v.offsetX, v.offsetY, c.width * v.scale, c.height * v.scale);

  const cw = c.width, ch = c.height;
  const topeY = cal.frame.tope / 100 * ch;
  const baseY = cal.frame.base / 100 * ch;
  const izqX  = cal.frame.izq  / 100 * cw;
  const derX  = cal.frame.der  / 100 * cw;
  const bandaY = cal.banda / 100 * ch;

  // Red jar rectangle
  ctx.strokeStyle = 'rgba(255, 80, 80, 0.9)';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  drawHLine(topeY, 'TOPE');
  drawHLine(baseY, 'BASE');
  drawVLine(izqX,  'IZQ');
  drawVLine(derX,  'DER');

  // Orange band line (red rubber band position)
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = 'rgba(255, 152, 0, 0.95)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, bandaY); ctx.lineTo(cw, bandaY);
  ctx.stroke();
  ctx.save();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(255,152,0,0.95)';
  ctx.font = 'bold 12px sans-serif';
  ctx.fillText('BANDA', 4, bandaY - 4);
  ctx.restore();
}

function drawHLine(y, label) {
  const ctx = cal.ctx, c = cal.canvas;
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
  const ctx = cal.ctx, c = cal.canvas;
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

// ─── interaction ───────────────────────────────────────────────────────
const HIT_THRESH = 12;
function getMousePos(e) {
  const r = cal.canvas.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}
function hitTest(x, y) {
  const cw = cal.canvas.width, ch = cal.canvas.height;
  const f = cal.frame;
  const topeY = f.tope / 100 * ch;
  const baseY = f.base / 100 * ch;
  const izqX  = f.izq  / 100 * cw;
  const derX  = f.der  / 100 * cw;
  const bandaY = cal.banda / 100 * ch;
  if (Math.abs(bandaY - y) < HIT_THRESH) return 'banda';
  if (Math.abs(topeY - y)  < HIT_THRESH) return 'f_tope';
  if (Math.abs(baseY - y)  < HIT_THRESH) return 'f_base';
  if (Math.abs(izqX  - x)  < HIT_THRESH) return 'f_izq';
  if (Math.abs(derX  - x)  < HIT_THRESH) return 'f_der';
  return null;
}
function cursorFor(hit) {
  if (hit === 'banda' || hit === 'f_tope' || hit === 'f_base') return 'ns-resize';
  if (hit === 'f_izq' || hit === 'f_der') return 'ew-resize';
  return 'grab';
}

// Event handlers — bound/unbound by wireEvents/unwireEvents so multiple opens
// don't stack duplicate listeners.
function onMouseDown(e) {
  const { x, y } = getMousePos(e);
  const forcePan = e.altKey || e.shiftKey || e.button === 1;
  const hit = forcePan ? null : hitTest(x, y);
  if (hit) cal.dragging = hit;
  else cal.panning = { lastX: x, lastY: y };
  cal.canvas.style.cursor = 'grabbing';
  e.preventDefault();
}
function onMouseMove(e) {
  const { x, y } = getMousePos(e);
  if (cal.panning) {
    cal.view.offsetX += x - cal.panning.lastX;
    cal.view.offsetY += y - cal.panning.lastY;
    cal.panning.lastX = x; cal.panning.lastY = y;
    render();
    return;
  }
  if (cal.dragging) {
    const cw = cal.canvas.width, ch = cal.canvas.height;
    const d = cal.dragging;
    if (d === 'banda') {
      cal.banda = Math.max(0, Math.min(100, y / ch * 100));
    } else if (d === 'f_tope' || d === 'f_base') {
      cal.frame[d.slice(2)] = Math.max(0, Math.min(100, y / ch * 100));
    } else if (d === 'f_izq' || d === 'f_der') {
      cal.frame[d.slice(2)] = Math.max(0, Math.min(100, x / cw * 100));
    }
    render();
    return;
  }
  cal.canvas.style.cursor = cursorFor(hitTest(x, y));
}
function onMouseUp() {
  cal.dragging = null;
  cal.panning = null;
  if (cal.canvas) cal.canvas.style.cursor = 'crosshair';
}
function onWheel(e) {
  e.preventDefault();
  const { x, y } = getMousePos(e);
  const old = cal.view.scale;
  const factor = e.deltaY > 0 ? (1 / 1.15) : 1.15;
  const next = Math.max(0.5, Math.min(10, old * factor));
  if (next === old) return;
  cal.view.offsetX = x - (x - cal.view.offsetX) * (next / old);
  cal.view.offsetY = y - (y - cal.view.offsetY) * (next / old);
  cal.view.scale = next;
  render();
}
function onKey(e) {
  if (!isCalibrating) return;
  if (e.key === 'Escape') closeModal();
  else if (e.key === 'Enter') saveCalibration();
  else if (e.key === '0') {
    cal.view = { scale: 1, offsetX: 0, offsetY: 0 };
    render();
  } else if (e.key === 'r' || e.key === 'R') {
    cal.frame = { ...DEFAULT_FRAME };
    cal.banda = DEFAULT_BANDA;
    cal.view = { scale: 1, offsetX: 0, offsetY: 0 };
    render();
  }
}
function onResize() { fitCanvas(); }

function wireEvents() {
  const c = cal.canvas;
  c.addEventListener('mousedown', onMouseDown);
  c.addEventListener('mousemove', onMouseMove);
  c.addEventListener('mouseup',   onMouseUp);
  c.addEventListener('mouseleave', onMouseUp);
  c.addEventListener('wheel', onWheel, { passive: false });
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', onResize);
  document.getElementById('calibSaveBtn')?.addEventListener('click', saveCalibration);
  document.getElementById('calibCancelBtn')?.addEventListener('click', closeModal);
  document.getElementById('calibCloseBtn')?.addEventListener('click', closeModal);
}
function unwireEvents() {
  const c = cal.canvas;
  if (!c) return;
  c.removeEventListener('mousedown', onMouseDown);
  c.removeEventListener('mousemove', onMouseMove);
  c.removeEventListener('mouseup',   onMouseUp);
  c.removeEventListener('mouseleave', onMouseUp);
  c.removeEventListener('wheel', onWheel);
  document.removeEventListener('keydown', onKey);
  window.removeEventListener('resize', onResize);
}
