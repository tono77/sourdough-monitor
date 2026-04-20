// ─── Growth data helpers ───

// Median filter on raw array (removes spike outliers from Claude's noise)
export function medianSmooth(values, window = 5) {
    return values.map((v, i) => {
        const half = Math.floor(window / 2);
        const start = Math.max(0, i - half);
        const end = Math.min(values.length, i + half + 1);
        const slice = [...values.slice(start, end)].sort((a, b) => a - b);
        return slice[Math.floor(slice.length / 2)];
    });
}

// Build level data for display with Multi-Cycle support.
// v2: uses altura_pct (absolute jar level 0-100%) when available,
// falls back to nivel_pct (legacy growth %) with median smoothing.
export function buildGrowthData(measurements) {
    const validMeds = measurements.filter(m =>
        m.altura_pct != null || m.crecimiento_pct != null || m.nivel_pct != null || m.is_ciclo === true
    );
    if (validMeds.length === 0) return null;

    const growthArr = [];
    const outputMeds = [];

    // 1. Isolate chunks between user 'ciclo' events (Feeding)
    const chunks = [];
    let currentChunk = [];
    validMeds.forEach(m => {
        if (m.is_ciclo === true) {
            if (currentChunk.length > 0) chunks.push(currentChunk);
            currentChunk = [];
        } else {
            currentChunk.push(m);
        }
    });
    if (currentChunk.length > 0) chunks.push(currentChunk);

    // 2. Process each chunk
    chunks.forEach(chunk => {
        // Prefer altura_pct (v2 field, absolute jar level)
        const hasV2 = chunk.some(m => m.altura_pct != null);

        if (hasV2) {
            // v2 path: use absolute jar level directly
            chunk.forEach(m => {
                const val = m.altura_pct != null ? parseFloat(m.altura_pct) : 0;
                growthArr.push(val);
                outputMeds.push(m);
            });
        } else {
            // Legacy path: smooth nivel_pct values
            const rawNiveles = chunk.map(m => parseFloat(m.nivel_pct));
            const chunkSmoothed = medianSmooth(rawNiveles, 5);
            const isLatestChunk = (chunk === chunks[chunks.length - 1]);
            chunkSmoothed.forEach((v, i) => {
                const isAbsoluteLast = isLatestChunk && (i === chunkSmoothed.length - 1);
                const finalVal = isAbsoluteLast ? rawNiveles[i] : (Number.isNaN(v) ? 0 : v);
                growthArr.push(finalVal);
                outputMeds.push(chunk[i]);
            });
        }
    });

    return { validMeds: outputMeds, growthArr };
}

// ─── Timer ───
let timerInterval = null;

export function startTimer(startIso) {
    if (timerInterval) clearInterval(timerInterval);
    const el = document.getElementById('elapsedTimer');
    const update = () => {
        const diff = Math.max(0, new Date() - new Date(startIso));
        const h = Math.floor(diff / 3600000);
        const m = Math.floor((diff % 3600000) / 60000);
        const s = Math.floor((diff % 60000) / 1000);
        el.textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    };
    update();
    timerInterval = setInterval(update, 1000);
}

export function clearTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = null;
}

export function getTimerInterval() {
    return timerInterval;
}

// ─── Formatting helpers ───
export function formatTime(isoString) {
    const t = new Date(isoString);
    return t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export async function promptNewCycle(db, collection, addDoc, currentSessionId, startCalibration, onCycleMarked, doc, updateDoc, setDoc) {
    if (!currentSessionId) return;
    const note = prompt("Marca un Nuevo Ciclo de Alimentacion.\nAnade una nota opcional (ej: 'Alimentado ratio 1:2:2'):");
    if (note === null) return; // Se cancelo

    const medsRef = collection(db, 'sesiones', currentSessionId, 'mediciones');
    try {
        await addDoc(medsRef, {
            timestamp: new Date().toISOString(),
            is_ciclo: true,
            notas: note ? `🔄 CICLO: ${note}` : '🔄 Nuevo ciclo de alimentacion',
            confianza: 5
        });
    } catch (err) {
        console.error("Error creating cycle:", err);
        alert("Hubo un error anadiendo el nuevo ciclo.");
        return;
    }

    // A new cycle resets crecimiento to 0%, so the "ventana para pan" banner
    // (which only makes sense while dough is above the threshold) should
    // disappear immediately rather than wait for the next capture.
    if (typeof doc === "function" && typeof updateDoc === "function") {
        try {
            await updateDoc(doc(db, 'sesiones', currentSessionId), {
                ventana_pan_activa: false,
            });
        } catch (e) {
            console.warn("Could not reset ventana_pan_activa:", e);
        }
    }

    // Wake from refrigerador (if any) and request a fresh capture — a just
    // refreshed masa looks nothing like the last photo, so relying on the
    // previous frame for calibration produces misleading labels.
    if (typeof doc === "function" && typeof setDoc === "function") {
        try {
            await setDoc(doc(db, 'app_config', 'state'), {
                is_hibernating: false,
                capture_requested_at: new Date().toISOString(),
            }, { merge: true });
        } catch (e) {
            console.warn("Could not request fresh capture:", e);
        }
    }

    // A new cycle means the jar likely moved (refresh) so anything sticky from
    // the previous cycle (e.g. the remembered correction frame) must be
    // cleared before the next correction picks up stale coordinates.
    if (typeof onCycleMarked === "function") onCycleMarked();

    // Cada ciclo nuevo requiere recalibrar — el jar puede haberse movido al
    // refrescar la masa. Abre el modal de calibración inmediatamente.
    if (typeof startCalibration === "function") {
        startCalibration();
    } else {
        alert("Nuevo ciclo marcado. Las siguientes lecturas empezaran desde 0%.");
    }
}
