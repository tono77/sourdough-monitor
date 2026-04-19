// ─── Measurement Detail Modal ───
// Shows photo + editable fields when clicking a chart data point

let _db = null;
let _doc = null;
let _updateDoc = null;
let _deleteDoc = null;
let _getSessionId = null;

export function initMeasurementDetail(db, doc, updateDoc, deleteDoc, getSessionId) {
    _db = db;
    _doc = doc;
    _updateDoc = updateDoc;
    _deleteDoc = deleteDoc;
    _getSessionId = getSessionId;

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('measurementDetail');
            if (modal && modal.classList.contains('open')) closeMeasurementDetail();
        }
    });
}

export function openMeasurementDetail(point) {
    const modal = document.getElementById('measurementDetail');
    if (!modal || !point) return;

    // Photo
    const img = document.getElementById('mdPhoto');
    if (point.foto_url) {
        img.src = point.foto_url;
        img.style.display = 'block';
        img.onerror = () => {
            if (point.foto_drive_id) {
                img.onerror = () => { img.style.display = 'none'; };
                img.src = `https://drive.google.com/uc?id=${point.foto_drive_id}`;
            } else {
                img.style.display = 'none';
            }
        };
    } else {
        img.style.display = 'none';
    }

    // Info
    const ts = new Date(point.timestamp);
    document.getElementById('mdTimestamp').textContent =
        ts.toLocaleString('es', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Altura comparison: fused vs ML. Helps assess ML model accuracy at a glance.
    const fused = point.altura_pct;
    const ml = point.ml_altura_pct;
    const fusedStr = (typeof fused === 'number') ? `${fused.toFixed(1)}%` : '--';
    const mlStr = (typeof ml === 'number') ? `${ml.toFixed(1)}%` : '—';
    document.getElementById('mdAlturaFused').textContent = fusedStr;
    document.getElementById('mdAlturaMl').textContent = mlStr;
    const deltaEl = document.getElementById('mdAlturaDelta');
    if (typeof fused === 'number' && typeof ml === 'number') {
        const delta = ml - fused;
        const sign = delta >= 0 ? '+' : '';
        deltaEl.textContent = `${sign}${delta.toFixed(1)}%`;
        deltaEl.style.color = Math.abs(delta) < 5 ? '#4ade80' : (Math.abs(delta) < 15 ? '#ffd700' : '#ef4444');
    } else {
        deltaEl.textContent = '—';
        deltaEl.style.color = '';
    }

    // Populate editable fields
    const growth = point.crecimiento_pct != null ? point.crecimiento_pct : (point.nivel_pct || '');
    document.getElementById('mdCrecimiento').value = typeof growth === 'number' ? growth.toFixed(1) : growth;
    document.getElementById('mdBurbujas').value = point.burbujas || 'ninguna';
    document.getElementById('mdTextura').value = point.textura || 'lisa';

    // Store measurement ID for saving
    modal.dataset.measurementId = point._id || '';

    // Show
    modal.classList.add('open');
}

export function closeMeasurementDetail() {
    document.getElementById('measurementDetail').classList.remove('open');
}

export async function saveMeasurementDetail() {
    const modal = document.getElementById('measurementDetail');
    const measurementId = modal.dataset.measurementId;
    const sessionId = _getSessionId();

    if (!measurementId || !sessionId || !_db) {
        alert('Error: no se pudo identificar la medicion.');
        return;
    }

    const newCrecimiento = parseFloat(document.getElementById('mdCrecimiento').value);
    const newBurbujas = document.getElementById('mdBurbujas').value;
    const newTextura = document.getElementById('mdTextura').value;

    if (isNaN(newCrecimiento)) {
        alert('Ingresa un valor numerico valido para el crecimiento.');
        return;
    }

    const saveBtn = document.getElementById('mdSaveBtn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Guardando...';

    try {
        const mRef = _doc(_db, 'sesiones', sessionId, 'mediciones', measurementId);
        await _updateDoc(mRef, {
            nivel_pct: newCrecimiento,
            crecimiento_pct: newCrecimiento,
            burbujas: newBurbujas,
            textura: newTextura,
            is_manual_override: true
        });

        saveBtn.textContent = 'Guardado!';
        setTimeout(() => {
            closeMeasurementDetail();
            saveBtn.disabled = false;
            saveBtn.textContent = 'Guardar correccion';
        }, 800);
    } catch (e) {
        console.error('Error saving correction:', e);
        alert('Error al guardar: ' + e.message);
        saveBtn.disabled = false;
        saveBtn.textContent = 'Guardar correccion';
    }
}

export async function deleteMeasurement() {
    const modal = document.getElementById('measurementDetail');
    const measurementId = modal.dataset.measurementId;
    const sessionId = _getSessionId();

    if (!measurementId || !sessionId || !_db) {
        alert('Error: no se pudo identificar la medicion.');
        return;
    }

    if (!confirm('¿Eliminar esta medicion? Esta accion no se puede deshacer.')) return;

    const deleteBtn = document.getElementById('mdDeleteBtn');
    deleteBtn.disabled = true;
    deleteBtn.textContent = 'Eliminando...';

    try {
        const mRef = _doc(_db, 'sesiones', sessionId, 'mediciones', measurementId);
        await _deleteDoc(mRef);
        closeMeasurementDetail();
        deleteBtn.disabled = false;
        deleteBtn.textContent = 'Eliminar medicion';
    } catch (e) {
        console.error('Error deleting measurement:', e);
        alert('Error al eliminar: ' + e.message);
        deleteBtn.disabled = false;
        deleteBtn.textContent = 'Eliminar medicion';
    }
}
