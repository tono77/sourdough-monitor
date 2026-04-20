import { initializeApp } from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js';
import {
  getAuth, GoogleAuthProvider, signInWithPopup, signOut as fbSignOut, onAuthStateChanged,
} from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js';
import {
  getFirestore, collection, query, orderBy, limit, onSnapshot, doc, updateDoc, addDoc, setDoc,
} from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js';

import { renderHome, setPeakMode, renderMlStats } from './home.js';
import { openCalibrate } from './calibrate.js';

const firebaseConfig = {
  apiKey: "AIzaSyCvH1nqbrIeakI5P5AuGTuEgDtL3SV_kNo",
  authDomain: "sourdough-monitor-app.firebaseapp.com",
  projectId: "sourdough-monitor-app",
  storageBucket: "sourdough-monitor-app.firebasestorage.app",
  messagingSenderId: "231699057388",
  appId: "1:231699057388:web:7685b1795464dc4cc173c9",
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

const state = {
  session: null,
  measurements: [],
  user: null,
  isHibernating: false,
  unsubs: { meds: null, sessionDoc: null, sessions: null, appConfig: null, retrain: null },
  lastRetrainSuccessAt: null,
};

window.signInWithGoogle = async () => {
  try { await signInWithPopup(auth, new GoogleAuthProvider()); }
  catch (e) { alert('Error al iniciar sesión: ' + e.message); }
};
window.signOut = () => fbSignOut(auth);

onAuthStateChanged(auth, user => {
  const login = document.getElementById('loginScreen');
  const mobApp = document.getElementById('mobileApp');
  if (user) {
    state.user = user;
    login.style.display = 'none';
    mobApp.classList.add('visible');
    mobApp.removeAttribute('aria-hidden');
    document.getElementById('mUserFoot').textContent = (user.email || '').toUpperCase();
    subscribeAppConfig();
    subscribeSessions();
    subscribeRetrainState();
    wireShellEvents();
  } else {
    state.user = null;
    login.style.display = 'flex';
    mobApp.classList.remove('visible');
    mobApp.setAttribute('aria-hidden', 'true');
    Object.values(state.unsubs).forEach(u => u && u());
    state.unsubs = { meds: null, sessionDoc: null, sessions: null, appConfig: null, retrain: null };
  }
});

function subscribeAppConfig() {
  if (state.unsubs.appConfig) state.unsubs.appConfig();
  state.unsubs.appConfig = onSnapshot(doc(db, 'app_config', 'state'), snap => {
    state.isHibernating = !!(snap.exists() && snap.data().is_hibernating);
    renderCurrent();
  });
}

function subscribeRetrainState() {
  if (state.unsubs.retrain) state.unsubs.retrain();
  let lastKey = null;
  state.unsubs.retrain = onSnapshot(doc(db, 'app_config', 'retrain_state'), snap => {
    if (!snap.exists()) { renderMlStats(null); lastKey = null; return; }
    const d = snap.data();
    renderMlStats(d);

    const key = `${d.state}|${d.step || ''}`;
    const isNewTransition = key !== lastKey;
    lastKey = key;

    if ((d.state === 'running' || d.state === 'requested') && isNewTransition) {
      toast(`🧠 ${d.message || 'Reentrenando…'}`);
    } else if (d.state === 'success' && d.finished_at && d.finished_at !== state.lastRetrainSuccessAt) {
      state.lastRetrainSuccessAt = d.finished_at;
      const finishedMs = new Date(d.finished_at).getTime();
      // Only toast fresh successes (within 90s) so page reloads don't re-alert.
      if (!Number.isNaN(finishedMs) && Date.now() - finishedMs < 90_000) {
        toast(buildRetrainToast(d), 7000);
      }
    } else if (d.state === 'error' && isNewTransition) {
      toast('❌ Retrain falló: ' + (d.error || d.message || 'logs'));
    }
  });
}

function buildRetrainToast(d) {
  const parts = [];
  if (typeof d.mae === 'number') parts.push(`MAE ${d.mae.toFixed(2)}%`);
  if (typeof d.prev_mae === 'number' && typeof d.mae === 'number') {
    const delta = d.mae - d.prev_mae;
    const arrow = delta <= 0 ? '▼' : '▲';
    parts.push(`${arrow}${Math.abs(delta).toFixed(2)}%`);
  }
  if (d.total_samples != null) parts.push(`${d.total_samples} muestras`);
  return '✅ Retrain OK · ' + (parts.join(' · ') || 'listo');
}

function subscribeSessions() {
  if (state.unsubs.sessions) state.unsubs.sessions();
  const q = query(collection(db, 'sesiones'), orderBy('fecha', 'desc'), limit(20));
  state.unsubs.sessions = onSnapshot(q, snap => {
    const sessions = snap.docs.map(d => ({ id: d.id, ...d.data() }));
    if (!sessions.length) return;
    const active = sessions.find(s => s.estado === 'activa') || sessions[0];
    if (!state.session || state.session.id !== active.id) selectSession(active.id);
  });
}

function selectSession(sessionId) {
  if (state.unsubs.meds) state.unsubs.meds();
  if (state.unsubs.sessionDoc) state.unsubs.sessionDoc();

  const medsRef = collection(db, 'sesiones', sessionId, 'mediciones');
  state.unsubs.meds = onSnapshot(query(medsRef, orderBy('timestamp', 'asc')), snap => {
    state.measurements = snap.docs
      .map(d => ({ _id: d.id, ...d.data() }))
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    renderCurrent();
  });

  state.unsubs.sessionDoc = onSnapshot(doc(db, 'sesiones', sessionId), snap => {
    if (snap.exists()) {
      state.session = { id: sessionId, ...snap.data() };
      renderCurrent();
    }
  });
}

function renderCurrent() {
  if (!state.session) return;
  renderHome({
    session: state.session,
    measurements: state.measurements,
    isHibernating: state.isHibernating,
  });
  const peak = !!(state.session && state.session.ventana_pan_activa);
  setPeakMode(peak);
}

// ── Actions ──
async function toggleHibernation() {
  try {
    await setDoc(doc(db, 'app_config', 'state'), { is_hibernating: !state.isHibernating }, { merge: true });
    toast(state.isHibernating ? 'Despertando…' : 'Refrigerando…');
  } catch (e) {
    toast('Error: ' + (e.message || e));
  }
}

async function newCycle() {
  if (!state.session) return;
  const note = prompt('Marca un nuevo ciclo. Nota opcional (ej: "1:2:2"):');
  if (note === null) return;
  try {
    await addDoc(collection(db, 'sesiones', state.session.id, 'mediciones'), {
      timestamp: new Date().toISOString(),
      is_ciclo: true,
      notas: note ? `🔄 CICLO: ${note}` : '🔄 Nuevo ciclo',
      confianza: 5,
    });
    await updateDoc(doc(db, 'sesiones', state.session.id), { ventana_pan_activa: false });
    // Wake from refrigerador if needed and request a fresh capture — a
    // refreshed masa looks nothing like the previous photo, so the old frame
    // is misleading for training.
    const cfg = { capture_requested_at: new Date().toISOString() };
    if (state.isHibernating) cfg.is_hibernating = false;
    await setDoc(doc(db, 'app_config', 'state'), cfg, { merge: true });
    toast(state.isHibernating ? 'Despertando y tomando foto nueva…' : 'Ciclo marcado. Tomando foto nueva…');
    vibrate(15);
  } catch (e) {
    toast('Error: ' + (e.message || e));
  }
}

function openCalibrateFab() {
  if (!state.session) return;
  const queue = state.measurements.filter(m => !m.is_ciclo && !m.is_manual_override);
  if (queue.length === 0) {
    // No pending — open with latest measurement as single item for re-correction
    const latest = [...state.measurements].reverse().find(m => !m.is_ciclo);
    if (!latest) { toast('Sin mediciones aún'); return; }
    openCalibrate({
      db, doc, updateDoc,
      sessionId: state.session.id,
      session: state.session,
      queue: [latest],
      onSaved: () => toast('Medición corregida'),
    });
    return;
  }
  openCalibrate({
    db, doc, updateDoc,
    sessionId: state.session.id,
    session: state.session,
    queue,
    onSaved: () => toast('Calibración guardada'),
  });
  vibrate(10);
}

function openMenu() {
  const menu = document.getElementById('mMenu');
  menu.hidden = !menu.hidden;
}

async function requestRetrain() {
  if (!confirm('¿Reentrenar el modelo ML con todas las correcciones?\nToma ~2 min.')) return;
  try {
    await setDoc(doc(db, 'app_config', 'retrain_state'), {
      state: 'requested',
      requested_at: new Date().toISOString(),
      message: 'Solicitado desde móvil',
    }, { merge: true });
    toast('Reentrenamiento solicitado');
  } catch (e) { toast('Error: ' + (e.message || e)); }
}

function goDesktop() {
  const url = new URL(location.href);
  url.searchParams.set('view', 'desktop');
  location.href = url.toString();
}

function wireShellEvents() {
  document.getElementById('mBtnRefrigerar').onclick = () => { toggleHibernation(); vibrate(10); };
  document.getElementById('mBtnNuevoCiclo').onclick = newCycle;
  document.getElementById('mBtnMore').onclick = openMenu;
  document.getElementById('mFab').onclick = openCalibrateFab;

  document.getElementById('mMenu').onclick = (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    document.getElementById('mMenu').hidden = true;
    if (act === 'retrain') requestRetrain();
    else if (act === 'desktop') goDesktop();
    else if (act === 'signout') fbSignOut(auth);
  };

  document.addEventListener('click', (e) => {
    const menu = document.getElementById('mMenu');
    if (menu.hidden) return;
    if (menu.contains(e.target)) return;
    if (e.target.closest('#mBtnMore')) return;
    menu.hidden = true;
  });

  document.addEventListener('m-tl-click', (e) => {
    const m = e.detail && e.detail.measurement;
    if (!m || !state.session) return;
    openCalibrate({
      db, doc, updateDoc,
      sessionId: state.session.id,
      session: state.session,
      queue: [m],
      onSaved: () => toast('Corrección guardada'),
    });
    vibrate(10);
  });
}

function vibrate(pattern) {
  if (navigator.vibrate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    navigator.vibrate(pattern);
  }
}

let toastTimer = null;
function toast(msg, durationMs = 2500) {
  const el = document.getElementById('mToast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, durationMs);
}

// Expose for calibrate.js callback usage
window.__mobileToast = toast;
