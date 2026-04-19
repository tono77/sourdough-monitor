// Measurement detail + altura corrector (desktop).
// Uses the shared jar-frame component: 4 corner handles define the jar bounds
// and a draggable green surface line marks the masa level. On save, writes
// the corrected altura_pct + manual_* frame coords so retraining can reuse
// them as labels, same payload the mobile calibrate screen produces.

import { createJarFrame } from './shared/jar-frame.js';

const DEFAULT_FRAME = { tope: 20, base: 88, izq: 30, der: 70 };

let _db = null;
let _doc = null;
let _updateDoc = null;
let _deleteDoc = null;
let _getSessionId = null;

// Sticky frame across corrections in a single page session (cleared when the
// user marks a new cycle, which likely means the jar moved).
let rememberedFrame = null;

let isOpen = false;
let jar = null;
let currentPoint = null;

export function initMeasurementDetail(db, docFn, updateDocFn, deleteDocFn, getSessionId) {
  _db = db;
  _doc = docFn;
  _updateDoc = updateDocFn;
  _deleteDoc = deleteDocFn;
  _getSessionId = getSessionId;
}

export function clearRememberedFrame() {
  rememberedFrame = null;
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
  const host = document.getElementById('mdJarFrame');
  if (!modal || !host) return;

  isOpen = true;
  currentPoint = point;

  populateHeader(point);
  populateFields(point);

  const saveBtn = document.getElementById('mdSaveBtn');
  if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Guardar corrección'; }
  const delBtn = document.getElementById('mdDeleteBtn');
  if (delBtn) { delBtn.disabled = false; delBtn.textContent = 'Eliminar medición'; }

  if (jar) jar.destroy();
  jar = createJarFrame(host, {
    onChange: ({ altura }) => {
      const out = document.getElementById('mdAlturaCorrected');
      if (out) out.textContent = altura.toFixed(1);
    },
  });

  fetchSessionCalibration().then(sessionCal => {
    let frame;
    if (typeof point.manual_tope_y_pct === 'number') {
      frame = {
        tope: point.manual_tope_y_pct, base: point.manual_base_y_pct,
        izq: point.manual_izq_x_pct, der: point.manual_der_x_pct,
      };
    } else if (rememberedFrame) {
      frame = { ...rememberedFrame };
    } else if (sessionCal) {
      frame = { tope: sessionCal.tope, base: sessionCal.base, izq: sessionCal.izq, der: sessionCal.der };
    } else {
      frame = { ...DEFAULT_FRAME };
    }
    jar.setFrame(frame);

    if (typeof point.manual_surface_y_pct === 'number') {
      jar.setSurface(point.manual_surface_y_pct);
    } else {
      const alt = (typeof point.altura_pct === 'number') ? point.altura_pct : 50;
      jar.setSurfaceFromAltura(alt);
    }
    jar.setImage(photoSrc);

    const out = document.getElementById('mdAlturaCorrected');
    if (out) out.textContent = jar.getState().altura.toFixed(1);
  });

  document.addEventListener('keydown', onKey);
  modal.classList.add('open');
}

export function closeMeasurementDetail() {
  const modal = document.getElementById('measurementDetail');
  if (modal) modal.classList.remove('open');
  document.removeEventListener('keydown', onKey);
  if (jar) { jar.destroy(); jar = null; }
  isOpen = false;
  currentPoint = null;
}

export async function deleteMeasurement() {
  const m = currentPoint;
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

export async function saveMeasurementDetail() {
  const m = currentPoint;
  const sid = _getSessionId();
  if (!m || !m._id || !sid || !_db || !jar) { alert("No se pudo identificar la medición."); return; }

  const { frame, surface, altura } = jar.getState();
  const burbujas = document.getElementById('mdBurbujas').value;
  const textura = document.getElementById('mdTextura').value;

  const btn = document.getElementById('mdSaveBtn');
  const resetBtn = () => {
    if (btn) { btn.disabled = false; btn.textContent = 'Guardar corrección'; }
  };
  if (btn) { btn.disabled = true; btn.textContent = 'Guardando…'; }

  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("timeout después de 10s")), 10000));

  try {
    const payload = {
      altura_pct: Math.round(altura * 10) / 10,
      burbujas, textura,
      is_manual_override: true,
      manual_tope_y_pct: frame.tope,
      manual_base_y_pct: frame.base,
      manual_izq_x_pct: frame.izq,
      manual_der_x_pct: frame.der,
      manual_surface_y_pct: surface,
      manual_corrected_at: new Date().toISOString(),
    };
    await Promise.race([
      _updateDoc(_doc(_db, 'sesiones', sid, 'mediciones', m._id), payload),
      timeout,
    ]);
    rememberedFrame = { ...frame };
    closeMeasurementDetail();
  } catch (e) {
    alert("Error al guardar: " + (e.message || e));
    resetBtn();
  }
}

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
  const ml = m.ml_altura_pct;
  document.getElementById('mdAlturaFused').textContent =
    (typeof fused === 'number') ? `${fused.toFixed(1)}%` : '—';
  document.getElementById('mdAlturaMl').textContent =
    (typeof ml === 'number') ? `${ml.toFixed(1)}%` : '—';

  document.getElementById('mdBurbujas').value = m.burbujas || 'ninguna';
  document.getElementById('mdTextura').value = m.textura || 'lisa';
}

async function fetchSessionCalibration() {
  const sid = _getSessionId();
  if (!sid) return null;
  try {
    const { getDoc } = await import('https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js');
    const snap = await getDoc(_doc(_db, 'sesiones', String(sid)));
    if (!snap.exists()) return null;
    const d = snap.data();
    const hasFrame = d.tope_y_pct != null && d.base_y_pct != null
      && d.izq_x_pct != null && d.der_x_pct != null;
    if (!hasFrame) return null;
    return { tope: d.tope_y_pct, base: d.base_y_pct, izq: d.izq_x_pct, der: d.der_x_pct };
  } catch (e) {
    console.warn("Could not fetch session calibration:", e);
    return null;
  }
}

function onKey(e) {
  if (!isOpen) return;
  if (e.key === 'Escape') closeMeasurementDetail();
  else if (e.key === 'Enter') saveMeasurementDetail();
}
