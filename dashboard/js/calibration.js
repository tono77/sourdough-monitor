// ─── Calibration overlay logic ───
import { openLightboxAt, closeLightbox } from './gallery.js';

let isCalibrating = false;
let calibStep = 0; // 1=base, 2=fondo, 3=tope, 4=izq, 5=der
let calibBaseY = 0;
let calibFondoY = 0;
let calibTopeY = 0;
let calibIzqX = 0;
let calibDerX = 0;

// References set by app.js at init time
let _db = null;
let _doc = null;
let _updateDoc = null;
let _getMeasurementsUnsubscribe = null;
let _getCurrentSessionId = null;

export function initCalibration(db, docFn, updateDocFn, getMeasurementsUnsubscribe, getCurrentSessionId) {
    _db = db;
    _doc = docFn;
    _updateDoc = updateDocFn;
    _getMeasurementsUnsubscribe = getMeasurementsUnsubscribe;
    _getCurrentSessionId = getCurrentSessionId;
}

export function getIsCalibrating() {
    return isCalibrating;
}

export function startCalibration() {
    if (!_getMeasurementsUnsubscribe() || !_getCurrentSessionId()) return;
    isCalibrating = true;
    calibStep = 1;
    openLightboxAt(0); // Open baseline photo
    document.getElementById('calibInstruction').style.display = 'block';
    document.getElementById('calibInstruction').textContent = 'Paso 1: Haz clic en la SUPERFICIE (Piso del Frasco)';
    document.getElementById('calibLineTope').style.display = 'none';
    document.getElementById('calibLineFondo').style.display = 'none';
    document.getElementById('calibLineBase').style.display = 'none';
    document.getElementById('calibLineIzq').style.display = 'none';
    document.getElementById('calibLineDer').style.display = 'none';
}

export async function handleLightboxClick(event) {
    if (!isCalibrating) return;
    const img = event.target;
    const rect = img.getBoundingClientRect();
    // Calculate percentage from top/left within the actual image layout
    const yPct = ((event.clientY - rect.top) / rect.height) * 100;
    const xPct = ((event.clientX - rect.left) / rect.width) * 100;

    if (calibStep === 1) {
        calibBaseY = yPct;
        const line = document.getElementById('calibLineBase');
        line.style.top = yPct + '%';
        line.style.display = 'block';
        calibStep = 2;
        document.getElementById('calibInstruction').textContent = 'Paso 2: Haz clic en la BANDA ROJA (Inicio de masa)';
    } else if (calibStep === 2) {
        calibFondoY = yPct;
        const line = document.getElementById('calibLineFondo');
        line.style.top = yPct + '%';
        line.style.display = 'block';
        calibStep = 3;
        document.getElementById('calibInstruction').textContent = 'Paso 3: Haz clic en el TOPE MAXIMO (Rebalse Y)';
    } else if (calibStep === 3) {
        calibTopeY = yPct;
        const line = document.getElementById('calibLineTope');
        line.style.top = yPct + '%';
        line.style.display = 'block';
        calibStep = 4;
        document.getElementById('calibInstruction').textContent = 'Paso 4: Haz clic en el BORDE IZQUIERDO del frasco (Eje X)';
    } else if (calibStep === 4) {
        calibIzqX = xPct;
        const line = document.getElementById('calibLineIzq');
        line.style.left = xPct + '%';
        line.style.display = 'block';
        calibStep = 5;
        document.getElementById('calibInstruction').textContent = 'Paso 5: Haz clic en el BORDE DERECHO del frasco (Eje X)';
    } else if (calibStep === 5) {
        calibDerX = xPct;
        const line = document.getElementById('calibLineDer');
        line.style.left = xPct + '%';
        line.style.display = 'block';

        document.getElementById('calibInstruction').textContent = 'Guardando calibracion 5-Puntos OpenCV...';

        try {
            const currentSessionId = _getCurrentSessionId();
            const sessionRef = _doc(_db, 'sesiones', currentSessionId);
            await _updateDoc(sessionRef, {
                base_y_pct: calibBaseY,
                fondo_y_pct: calibFondoY,
                tope_y_pct: calibTopeY,
                izq_x_pct: calibIzqX,
                der_x_pct: calibDerX,
                is_calibrated: 1
            });

            document.getElementById('calibInstruction').textContent = 'Calibracion OpenCV guardada!';
            setTimeout(() => {
                isCalibrating = false;
                calibStep = 0;
                document.getElementById('calibInstruction').style.display = 'none';
                document.getElementById('calibLineBase').style.display = 'none';
                document.getElementById('calibLineFondo').style.display = 'none';
                document.getElementById('calibLineTope').style.display = 'none';
                document.getElementById('calibLineIzq').style.display = 'none';
                document.getElementById('calibLineDer').style.display = 'none';
                closeLightbox();
            }, 1500);

        } catch(e) {
            alert("Error guardando calibracion: " + e.message);
            isCalibrating = false;
            document.getElementById('calibInstruction').style.display = 'none';
        }
    }
}
