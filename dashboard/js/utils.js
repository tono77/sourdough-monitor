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

// Build growth data for display with Multi-Cycle support.
// v2: uses crecimiento_pct (pre-calculated by backend) when available,
// falls back to nivel_pct with median smoothing for legacy data.
export function buildGrowthData(measurements) {
    const validMeds = measurements.filter(m =>
        m.crecimiento_pct != null || m.nivel_pct != null || m.is_ciclo === true
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
        // Prefer crecimiento_pct (v2 field, pre-computed growth)
        const hasV2 = chunk.some(m => m.crecimiento_pct != null);

        if (hasV2) {
            // v2 path: use backend-calculated growth directly
            chunk.forEach(m => {
                const val = m.crecimiento_pct != null ? parseFloat(m.crecimiento_pct) : 0;
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

// ─── Prompt-based actions (exposed to window from app.js) ───
export async function promptEditCrecimiento(db, doc, updateDoc, currentSessionId, allMeasurements) {
    if (!currentSessionId || allMeasurements.length === 0) {
        alert("No hay mediciones para corregir aun.");
        return;
    }

    // Edit the latest measurement explicitly
    const latestValid = [...allMeasurements].reverse().find(m => m.nivel_pct != null || m._id != null);
    if (!latestValid) return;

    const realId = latestValid._id || latestValid.timestamp.replace(":", "-").replace(".", "-");

    const currentVal = prompt(`Corrige el % medido por la IA para la ultima foto (${new Date(latestValid.timestamp).toLocaleTimeString()}):`,
                              latestValid.nivel_pct || "");
    if (currentVal !== null && currentVal.trim() !== "") {
        const newVal = parseFloat(currentVal);
        if (!isNaN(newVal)) {
            try {
                const mRef = doc(db, "sesiones", currentSessionId, "mediciones", realId);
                await updateDoc(mRef, {
                    nivel_pct: newVal,
                    is_manual_override: true,
                    notas: "Medicion corregida manualmente"
                });
                alert("Correccion guardada con exito! Esto ayudara al modelo a aprender.");
            } catch (e) {
                alert("Error al actualizar la lectura: " + e.message);
            }
        }
    }
}

export async function promptNewCycle(db, collection, addDoc, currentSessionId) {
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
        alert("Nuevo ciclo marcado exitosamente! Las siguientes lecturas empezaran desde 0%.");
    } catch (err) {
        console.error("Error creating cycle:", err);
        alert("Hubo un error anadiendo el nuevo ciclo.");
    }
}
