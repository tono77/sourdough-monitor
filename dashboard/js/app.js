// ─── Main App Entry Point ───
// Firebase imports & init, auth, state management, dashboard orchestration

import { initializeApp } from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js';
import {
    getAuth,
    GoogleAuthProvider,
    signInWithPopup,
    signOut as fbSignOut,
    onAuthStateChanged
} from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js';
import {
    getFirestore,
    collection,
    query,
    orderBy,
    limit,
    getDocs,
    doc,
    onSnapshot,
    where,
    updateDoc,
    addDoc,
    setDoc,
    deleteDoc
} from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js';
import { getMessaging, getToken, onMessage } from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-messaging.js';

import { initCharts, updateCharts, setOnPointClick } from './charts.js';
import { initMeasurementDetail, openMeasurementDetail, closeMeasurementDetail, saveMeasurementDetail, deleteMeasurement, clearRememberedFrame } from './measurement-detail.js';
import { openLightbox, openLightboxAt, openLightboxSrc, lightboxNav, closeLightbox, updateLatestPhoto, updateGallery, setupLightboxKeyboard } from './gallery.js';
import { initCalibration, startCalibration, getIsCalibrating } from './calibration.js';
import { buildGrowthData, startTimer, clearTimer, promptNewCycle } from './utils.js';

// ─── Firebase config ───
const firebaseConfig = {
    apiKey: "AIzaSyCvH1nqbrIeakI5P5AuGTuEgDtL3SV_kNo",
    authDomain: "sourdough-monitor-app.firebaseapp.com",
    projectId: "sourdough-monitor-app",
    storageBucket: "sourdough-monitor-app.firebasestorage.app",
    messagingSenderId: "231699057388",
    appId: "1:231699057388:web:7685b1795464dc4cc173c9"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

// ─── Expose auth functions to window (for onclick in HTML) ───
window.signInWithGoogle = async () => {
    const provider = new GoogleAuthProvider();
    try {
        await signInWithPopup(auth, provider);
    } catch (e) {
        console.error('Login error:', e);
        alert('Error al iniciar sesion: ' + e.message);
    }
};

window.signOut = () => fbSignOut(auth);

// ─── State ───
let currentSessionId = null;
let measurementsUnsubscribe = null;
let sessionDocUnsubscribe = null;
let sessionsUnsubscribe = null;
let allMeasurements = [];
let appConfigUnsubscribe = null;
let isHibernating = false;
let messaging = null;
let rerenderDashboard = null; // set by selectSession so loadAppConfig can re-render on wake

// ─── Initialize calibration module with Firebase refs ───
initCalibration(
    db, doc, updateDoc,
    () => currentSessionId,
    () => allMeasurements,
);

// ─── Expose gallery/calibration functions to window (for onclick in HTML) ───
window.openLightbox = openLightbox;
window.openLightboxAt = openLightboxAt;
window.openLightboxSrc = openLightboxSrc;
window.lightboxNav = lightboxNav;
window.closeLightbox = closeLightbox;
window.startCalibration = startCalibration;
window.closeMeasurementDetail = closeMeasurementDetail;
window.saveMeasurementDetail = saveMeasurementDetail;
window.deleteMeasurement = deleteMeasurement;

// ─── Expose utility functions to window ───
window.promptNewCycle = () => promptNewCycle(db, collection, addDoc, currentSessionId, () => startCalibration(), clearRememberedFrame, doc, updateDoc);

// ─── Retrain trigger + live status banner ───
let retrainStateUnsubscribe = null;
window.requestRetrain = async () => {
    if (!confirm("¿Reentrenar el modelo ML con todas las correcciones acumuladas?\n\nEsto toma ~2 min. El monitor se reinicia automáticamente al terminar.")) return;
    try {
        await setDoc(doc(db, 'app_config', 'retrain_state'), {
            state: 'requested',
            requested_at: new Date().toISOString(),
            message: 'Solicitado desde el dashboard',
        }, { merge: true });
    } catch (e) {
        alert("No se pudo solicitar el retrain: " + (e.message || e));
    }
};

function subscribeRetrainState() {
    if (retrainStateUnsubscribe) retrainStateUnsubscribe();
    retrainStateUnsubscribe = onSnapshot(doc(db, 'app_config', 'retrain_state'), (snap) => {
        const banner = document.getElementById('retrainBanner');
        const bMsg   = document.getElementById('retrainBannerMsg');
        const bTitle = banner ? banner.querySelector('.calib-text h3') : null;
        const btn    = document.getElementById('retrainBtn');
        if (!banner || !btn) return;
        if (!snap.exists()) {
            banner.style.display = 'none';
            btn.disabled = false;
            btn.textContent = '🧠 Reentrenar ML';
            return;
        }
        const d = snap.data();
        const state = d.state;
        const mae = (typeof d.mae === 'number') ? d.mae.toFixed(2) + '%' : null;

        // Stale-success: if the retrain finished a while ago, don't keep
        // showing the "done" banner forever on fresh page loads.
        if (state === 'success' && d.finished_at) {
            const finishedMs = new Date(d.finished_at).getTime();
            if (!Number.isNaN(finishedMs) && Date.now() - finishedMs > 60_000) {
                banner.style.display = 'none';
                btn.disabled = false;
                btn.textContent = '🧠 Reentrenar ML';
                return;
            }
        }

        if (state === 'requested' || state === 'running') {
            banner.style.display = 'flex';
            banner.style.borderColor = 'rgba(124,58,237,0.3)';
            if (bTitle) bTitle.textContent = 'Reentrenando modelo ML';
            bMsg.textContent = d.message || 'En curso…';
            btn.disabled = true;
            btn.textContent = '⏳ En curso…';
        } else if (state === 'success') {
            banner.style.display = 'flex';
            banner.style.borderColor = 'rgba(74,222,128,0.4)';
            if (bTitle) bTitle.textContent = 'Modelo reentrenado';
            bMsg.textContent = mae ? `✅ Listo (MAE ${mae}). Monitor reiniciándose…` : '✅ Listo. Monitor reiniciándose…';
            btn.disabled = false;
            btn.textContent = '🧠 Reentrenar ML';
            // Auto-hide shortly after first render of a fresh success
            setTimeout(() => { banner.style.display = 'none'; }, 8000);
        } else if (state === 'error') {
            banner.style.display = 'flex';
            banner.style.borderColor = 'rgba(239,68,68,0.4)';
            if (bTitle) bTitle.textContent = 'Error al reentrenar';
            bMsg.textContent = '❌ ' + (d.error || d.message || 'revisa logs del monitor');
            btn.disabled = false;
            btn.textContent = '🧠 Reentrenar ML';
        } else {
            banner.style.display = 'none';
            btn.disabled = false;
            btn.textContent = '🧠 Reentrenar ML';
        }
    });
}

// ─── Setup keyboard navigation (pass calibrating state getter) ───
setupLightboxKeyboard(getIsCalibrating);

// ─── Initialize measurement detail modal ───
initMeasurementDetail(db, doc, updateDoc, deleteDoc, () => currentSessionId);
setOnPointClick(openMeasurementDetail);

// ─── FCM Push Notifications ───
// VAPID key must be generated in Firebase Console > Project Settings > Cloud Messaging > Web Push certificates
const VAPID_KEY = 'BGTdEwlwka5fwP6OqimZYEGGfUJaQuMRgSMmut2e7ks6iSZ7zniNxJ_gTaGSPQhcQ8s4ZWRLnnk7G-qYpy1NGBM';

async function initPushNotifications() {
    try {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') return;

        const swReg = await navigator.serviceWorker.ready;
        messaging = getMessaging(app);

        const fcmToken = await getToken(messaging, {
            vapidKey: VAPID_KEY,
            serviceWorkerRegistration: swReg,
        });

        if (fcmToken) {
            // Save token to Firestore so the Python backend can send pushes
            await setDoc(doc(db, 'app_config', 'fcm_token'), {
                token: fcmToken,
                updated: new Date().toISOString(),
            });
            console.log('FCM token registered');
        }

        // Foreground messages: show in-app toast
        onMessage(messaging, (payload) => {
            const { title, body } = payload.notification || {};
            if (title) showToast(title, body);
        });
    } catch (err) {
        console.warn('Push notification init failed:', err);
    }
}

function showToast(title, body) {
    let toast = document.getElementById('pushToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'pushToast';
        toast.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);' +
            'background:var(--card-bg,#1a1a2e);color:#fff;padding:12px 20px;border-radius:12px;' +
            'box-shadow:0 4px 20px rgba(0,0,0,.5);z-index:9999;max-width:90vw;' +
            'border:1px solid var(--accent,#e94560);transition:opacity .3s;font-size:14px;';
        document.body.appendChild(toast);
    }
    toast.innerHTML = `<strong>${title}</strong><br><span style="opacity:.8">${body || ''}</span>`;
    toast.style.opacity = '1';
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => { toast.style.opacity = '0'; }, 5000);
}

// ─── Auth state ───
onAuthStateChanged(auth, user => {
    const loginScreen = document.getElementById('loginScreen');
    const appEl = document.getElementById('app');

    if (user) {
        loginScreen.style.display = 'none';
        appEl.classList.add('visible');

        // Show user info
        const avatar = document.getElementById('userAvatar');
        if (user.photoURL) {
            avatar.src = user.photoURL;
            avatar.style.display = 'block';
        }
        document.getElementById('userName').textContent = user.displayName || user.email;

        initPushNotifications();
        initCharts();
        loadSessions();
        loadAppConfig();
        subscribeRetrainState();
    } else {
        loginScreen.style.display = 'flex';
        appEl.classList.remove('visible');
        if (measurementsUnsubscribe) { measurementsUnsubscribe(); measurementsUnsubscribe = null; }
        if (sessionDocUnsubscribe)   { sessionDocUnsubscribe();   sessionDocUnsubscribe   = null; }
        if (sessionsUnsubscribe)     { sessionsUnsubscribe();     sessionsUnsubscribe     = null; }
        if (appConfigUnsubscribe)    { appConfigUnsubscribe();    appConfigUnsubscribe    = null; }
        if (retrainStateUnsubscribe) { retrainStateUnsubscribe(); retrainStateUnsubscribe = null; }
    }
});

// ─── App Config Listener ───
function loadAppConfig() {
    const stateRef = doc(db, 'app_config', 'state');
    if (appConfigUnsubscribe) appConfigUnsubscribe();

    appConfigUnsubscribe = onSnapshot(stateRef, (docSnap) => {
        const btn = document.getElementById('hibernateBtn');
        const badge = document.getElementById('statusBadge');
        const badgeText = document.getElementById('statusText');

        btn.style.display = 'flex';
        if (docSnap.exists() && docSnap.data().is_hibernating) {
            isHibernating = true;
            btn.innerHTML = '🌞 Despertar';

            // Override the active/inactive pill styling
            badge.className = 'status-badge hibernating';
            badgeText.textContent = 'Hibernando';
        } else {
            isHibernating = false;
            btn.innerHTML = '❄️ Refrigerar';

            // Re-render with current session data so the badge reflects the real
            // state (Monitoreando / Completada) instead of staying as "Cargando..."
            if (rerenderDashboard) {
                rerenderDashboard();
            } else {
                badge.className = 'status-badge inactive';
                badgeText.textContent = 'Cargando...';
            }
        }
    });
}

window.toggleHibernation = async () => {
    const stateRef = doc(db, 'app_config', 'state');
    try {
        await setDoc(stateRef, { is_hibernating: !isHibernating }, { merge: true });
    } catch (err) {
        console.error("Error toggling hibernation:", err);
        alert("Error al intentar cambiar el estado de hibernacion.");
    }
};

// ─── Load sessions list ───
async function loadSessions() {
    const sessionsRef = collection(db, 'sesiones');
    const q = query(sessionsRef, orderBy('fecha', 'desc'), limit(20));

    if (sessionsUnsubscribe) sessionsUnsubscribe();

    sessionsUnsubscribe = onSnapshot(q, snapshot => {
        const sessions = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        renderSessionChips(sessions);

        // Auto-select: prefer active, else most recent
        if (!currentSessionId && sessions.length > 0) {
            const active = sessions.find(s => s.estado === 'activa');
            selectSession((active || sessions[0]).id);
        }
    });
}

function renderSessionChips(sessions) {
    const grid = document.getElementById('sessionsGrid');
    if (!sessions.length) {
        grid.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No hay sesiones aun — el monitor aun no sincronizo datos.</div>';
        return;
    }

    grid.innerHTML = sessions.map(s => {
        const isActive = s.estado === 'activa';
        const isCurrent = currentSessionId === s.id;
        const count = s.num_mediciones || 0;
        const peak = s.peak_nivel ? `Peak: ${parseFloat(s.peak_nivel).toFixed(0)}%` : '';

        return `<div class="session-chip ${isCurrent ? 'active' : ''}" onclick="window._selectSession('${s.id}')">
            <div class="chip-date">
                <span class="chip-status ${isActive ? 'live' : 'done'}"></span>
                ${s.fecha || 'N/A'}
            </div>
            <div class="chip-meta">${count} med. ${peak}</div>
        </div>`;
    }).join('');
}

// ─── Select a session and subscribe to its measurements ───
window._selectSession = (sessionId) => selectSession(sessionId);

function selectSession(sessionId) {
    currentSessionId = sessionId;

    // Clean up previous listeners
    if (measurementsUnsubscribe) { measurementsUnsubscribe(); measurementsUnsubscribe = null; }
    if (sessionDocUnsubscribe)   { sessionDocUnsubscribe();   sessionDocUnsubscribe   = null; }

    // Shared state for this session
    let localMeasurements = [];
    let localSession = null;

    const render = () => {
        if (localSession) updateDashboard(localSession, localMeasurements);
    };
    rerenderDashboard = render;

    // 1. Subscribe to measurements subcollection
    const medsRef = collection(db, 'sesiones', sessionId, 'mediciones');
    const q = query(medsRef, orderBy('timestamp', 'asc'));
    measurementsUnsubscribe = onSnapshot(q, snapshot => {
        localMeasurements = snapshot.docs.map(d => ({ _id: d.id, ...d.data() }));
        // Sort array in memory
        localMeasurements.sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
        allMeasurements = localMeasurements;
        render();
    }, err => console.error('Measurements snapshot error:', err));

    // 2. Subscribe to session document independently
    sessionDocUnsubscribe = onSnapshot(doc(db, 'sesiones', sessionId), sessionDoc => {
        if (sessionDoc.exists()) {
            localSession = { id: sessionId, ...sessionDoc.data() };

            // Show or hide calib banner
            if (localSession.is_calibrated === 1) {
                document.getElementById('calibBanner').classList.remove('visible');
            } else if (localSession.estado === 'activa') {
                document.getElementById('calibBanner').classList.add('visible');
            }

            // Bread window state
            const breadBanner = document.getElementById('breadWindowBanner');
            const windowActive = localSession.ventana_pan_activa === true;

            if (windowActive) {
                breadBanner.classList.add('visible');
                const inicio = localSession.ventana_pan_inicio;
                if (inicio) {
                    const t = new Date(inicio);
                    document.getElementById('breadWindowInfo').textContent =
                        `Desde las ${t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })} — tu masa madre superó el 90%`;
                }
            } else {
                breadBanner.classList.remove('visible');
            }

            render();
        }
    }, err => console.error('Session doc snapshot error:', err));
}

// ─── Dashboard rendering ───
const bubbleDisplay = {
    'ninguna': { emoji: '⚪', text: 'Ninguna' },
    'pocas':   { emoji: '🟡', text: 'Pocas' },
    'muchas':  { emoji: '🟢', text: 'Muchas' }
};

const textureDisplay = {
    'lisa':       { emoji: '😴', text: 'Lisa' },
    'rugosa':     { emoji: '😊', text: 'Rugosa' },
    'muy_activa': { emoji: '🔥', text: 'Activa' }
};

function updateDashboard(session, measurements) {
    if (!session) return;

    const latest = measurements.length > 0 ? measurements[measurements.length - 1] : null;
    const isActive = session.estado === 'activa';

    // Status badge
    const badge = document.getElementById('statusBadge');
    badge.className = `status-badge ${isActive ? 'active' : 'inactive'}`;
    document.getElementById('statusText').textContent = isActive ? 'Monitoreando' : 'Completada';

    // Timer
    if (isActive && session.hora_inicio) {
        startTimer(session.hora_inicio);
    } else {
        clearTimer();
        document.getElementById('elapsedTimer').textContent =
            `${session.num_mediciones || measurements.length} mediciones`;
    }

    // ─── Cumulative growth data (median-smooth -> running max) ───
    const gd = buildGrowthData(measurements);
    const latestValidIdx = gd ? gd.growthArr.length - 1 : -1;
    const currentGrowth = latestValidIdx >= 0 ? gd.growthArr[latestValidIdx] : null;
    const prevGrowth    = latestValidIdx >= 1 ? gd.growthArr[latestValidIdx - 1] : null;

    // Level metric — prefer volumen_ml (absolute, from jar's printed scale)
    // and fall back to altura_pct when the ml scale isn't detected.
    if (latest) {
        const prevMed = gd && latestValidIdx >= 1 ? gd.validMeds[latestValidIdx - 1] : null;
        const hasMl = latest.volumen_ml != null;

        if (hasMl) {
            const currentMl = parseFloat(latest.volumen_ml);
            const prevMl = prevMed && prevMed.volumen_ml != null ? parseFloat(prevMed.volumen_ml) : null;

            document.getElementById('levelValue').textContent = `${currentMl.toFixed(0)}ml`;

            if (prevMl != null) {
                const diffMl = currentMl - prevMl;
                let arrow = '→', color = '#888';
                if (diffMl > 2) { arrow = '↑'; color = '#4caf50'; }
                else if (diffMl < -2) { arrow = '↓'; color = '#e94560'; }
                const sign = diffMl > 0 ? '+' : '';
                const sub = document.getElementById('levelSub');
                sub.textContent = `${arrow} ${sign}${diffMl.toFixed(0)}ml vs anterior`;
                sub.style.color = color;
            }
        } else {
            const currentLevel = latest.altura_pct != null ? parseFloat(latest.altura_pct) : null;
            const prevLevel = prevMed && prevMed.altura_pct != null ? parseFloat(prevMed.altura_pct) : null;

            document.getElementById('levelValue').textContent =
                currentLevel != null ? `${currentLevel.toFixed(0)}%` : '--';

            if (prevLevel != null && currentLevel != null) {
                const diff = currentLevel - prevLevel;
                let arrow = '→';
                let color = '#888';
                if (diff > 0.5) { arrow = '↑'; color = '#4caf50'; }
                else if (diff < -0.5) { arrow = '↓'; color = '#e94560'; }

                const sign = diff > 0 ? '+' : '';
                const sub = document.getElementById('levelSub');
                sub.textContent = `${arrow} ${sign}${diff.toFixed(1)}% vs anterior`;
                sub.style.color = color;
            }
        }

        // Show the two altura measurements side-by-side: the fused CV+Claude
        // reading ("Trad") and the ML model prediction. Hidden if neither is
        // available yet.
        const mlEl = document.getElementById('levelMlCompare');
        if (mlEl) {
            const fusedAltura = latest.altura_pct != null ? parseFloat(latest.altura_pct) : null;
            const mlAltura = latest.ml_altura_pct != null ? parseFloat(latest.ml_altura_pct) : null;
            const tradSpan = document.getElementById('levelTradValue');
            const mlSpan = document.getElementById('levelMlValue');
            if (tradSpan) tradSpan.textContent = fusedAltura != null ? `${fusedAltura.toFixed(0)}%` : '—';
            if (mlSpan)   mlSpan.textContent   = mlAltura != null    ? `${mlAltura.toFixed(0)}%`    : '—';
            mlEl.style.display = (fusedAltura != null || mlAltura != null) ? 'block' : 'none';
        }

        const bub = bubbleDisplay[latest.burbujas] || { emoji: '--', text: '--' };
        document.getElementById('bubblesValue').textContent = bub.emoji;
        document.getElementById('bubblesSub').textContent = bub.text;

        const tex = textureDisplay[latest.textura] || { emoji: '--', text: '--' };
        document.getElementById('textureValue').textContent = tex.emoji;
        document.getElementById('textureSub').textContent = tex.text;

        if (latest.notas) {
            document.getElementById('notesBar').style.display = 'flex';
            document.getElementById('notesText').textContent = latest.notas;
        } else {
            document.getElementById('notesBar').style.display = 'none';
        }
    }

    // Time card
    const ciclos = measurements.filter(m => m.is_ciclo === true);
    const latestCicloTs = ciclos.length > 0 ? Object.assign(ciclos[ciclos.length - 1]).timestamp : session.hora_inicio;

    if (latestCicloTs) {
        const start = new Date(latestCicloTs);
        const now = new Date();
        const hours = ((now - start) / 3600000).toFixed(1);
        document.getElementById('timeValue').textContent = `${hours}h`;
        document.getElementById('timeSub').textContent = `${measurements.length} mediciones`;
    }

    // Peak banner — validate using smooth running max
    // Hide if the fermento kept growing AFTER the detected peak (false peak)
    const rawPeak = measurements.find(m => m.es_peak === 1 || m.es_peak === true);
    let confirmedPeak = null;
    if (rawPeak && gd && gd.validMeds.length >= 5) {
        const peakIdx = gd.validMeds.findIndex(v => v.timestamp === rawPeak.timestamp);
        if (peakIdx >= 0) {
            const peakGrowth   = gd.growthArr[peakIdx];
            const latestGrowth = gd.growthArr[gd.growthArr.length - 1];
            // Only confirmed if sourdough didn't grow past the detected peak (within 2%)
            if (peakGrowth >= latestGrowth - 2) {
                confirmedPeak = { growth: peakGrowth, time: rawPeak.timestamp };
            }
        }
    }
    const peakBanner = document.getElementById('peakBanner');
    if (confirmedPeak) {
        peakBanner.classList.add('visible');
        document.getElementById('peakInfo').textContent =
            `Crecimiento maximo: +${confirmedPeak.growth.toFixed(0)}% a las ${new Date(confirmedPeak.time).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`;
    } else {
        peakBanner.classList.remove('visible');
    }

    updateCharts(measurements, gd, session);
    updateLatestPhoto(latest);
    updateGallery(measurements, gd, session);
}
