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
    setDoc
} from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js';

import { initCharts, updateCharts, setOnPointClick } from './charts.js';
import { initMeasurementDetail, openMeasurementDetail, closeMeasurementDetail, saveMeasurementDetail } from './measurement-detail.js';
import { openLightbox, openLightboxAt, openLightboxSrc, lightboxNav, closeLightbox, updateLatestPhoto, updateGallery, setupLightboxKeyboard } from './gallery.js';
import { initCalibration, startCalibration, handleLightboxClick, getIsCalibrating } from './calibration.js';
import { buildGrowthData, startTimer, clearTimer, promptEditCrecimiento, promptNewCycle } from './utils.js';

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
let lastBreadWindowState = null; // tracks ventana_pan_activa to detect changes

// ─── Initialize calibration module with Firebase refs ───
initCalibration(
    db, doc, updateDoc,
    () => measurementsUnsubscribe,
    () => currentSessionId
);

// ─── Expose gallery/calibration functions to window (for onclick in HTML) ───
window.openLightbox = openLightbox;
window.openLightboxAt = openLightboxAt;
window.openLightboxSrc = openLightboxSrc;
window.lightboxNav = lightboxNav;
window.closeLightbox = closeLightbox;
window.startCalibration = startCalibration;
window.handleLightboxClick = handleLightboxClick;
window.closeMeasurementDetail = closeMeasurementDetail;
window.saveMeasurementDetail = saveMeasurementDetail;

// ─── Expose utility functions to window ───
window.promptEditCrecimiento = () => promptEditCrecimiento(db, doc, updateDoc, currentSessionId, allMeasurements);
window.promptNewCycle = () => promptNewCycle(db, collection, addDoc, currentSessionId);

// ─── Setup keyboard navigation (pass calibrating state getter) ───
setupLightboxKeyboard(getIsCalibrating);

// ─── Initialize measurement detail modal ───
initMeasurementDetail(db, doc, updateDoc, () => currentSessionId);
setOnPointClick(openMeasurementDetail);

// ─── Web Notifications ───
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function sendNotification(title, body, icon = '🍞') {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body, icon: '/icons/icon-192.png', badge: '/icons/icon-192.png' });
    }
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

        requestNotificationPermission();
        initCharts();
        loadSessions();
        loadAppConfig();
    } else {
        loginScreen.style.display = 'flex';
        appEl.classList.remove('visible');
        if (measurementsUnsubscribe) { measurementsUnsubscribe(); measurementsUnsubscribe = null; }
        if (sessionDocUnsubscribe)   { sessionDocUnsubscribe();   sessionDocUnsubscribe   = null; }
        if (sessionsUnsubscribe)     { sessionsUnsubscribe();     sessionsUnsubscribe     = null; }
        if (appConfigUnsubscribe)    { appConfigUnsubscribe();    appConfigUnsubscribe    = null; }
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

            // Restore original class (we just assume it's loading/active to let
            // loadSessionDetails reset it to active or inactive based on latest measurement)
            badge.className = 'status-badge inactive';
            badgeText.textContent = 'Cargando...';
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
                        `Desde las ${t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })} — tu masa madre superó el 100%`;
                }
            } else {
                breadBanner.classList.remove('visible');
            }

            // Send browser notification on state change
            if (lastBreadWindowState !== null && windowActive !== lastBreadWindowState) {
                if (windowActive) {
                    sendNotification(
                        '🍞 ¡Ventana para Pan!',
                        'Tu masa madre superó el 100% de crecimiento. Es momento de hornear.'
                    );
                } else {
                    sendNotification(
                        '⏰ Ventana Cerrada',
                        'Tu masa madre bajó del 100%. La ventana para hornear se cerró.'
                    );
                }
            }
            lastBreadWindowState = windowActive;

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

    // Level metric
    if (latest) {
        document.getElementById('levelValue').textContent =
            currentGrowth != null ? (currentGrowth >= 0 ? `+${currentGrowth.toFixed(0)}%` : `${currentGrowth.toFixed(0)}%`) : '--';

        if (prevGrowth != null && currentGrowth != null) {
            const diff = currentGrowth - prevGrowth;
            let arrow = '→';
            let color = '#888';
            if (diff > 0) { arrow = '↑'; color = '#4caf50'; }
            else if (diff < 0) { arrow = '↓'; color = '#e94560'; }

            const sign = diff > 0 ? '+' : '';
            const sub = document.getElementById('levelSub');
            sub.textContent = `${arrow} ${sign}${diff.toFixed(1)}%`;
            sub.style.color = color;
            document.getElementById('levelVsAnterior').textContent = 'vs medicion anterior';
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
