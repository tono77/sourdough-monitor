// ─── Gallery & Lightbox module ───

let lightboxPhotos = [];  // [{url, driveId, time, deltaLabel}] ascending
let lightboxIndex = 0;

export function getLightboxPhotos() {
    return lightboxPhotos;
}

export function getLightboxIndex() {
    return lightboxIndex;
}

function showCurrentLightbox() {
    const p = lightboxPhotos[lightboxIndex];
    if (!p) return;
    document.getElementById('lightboxImg').src = p.url;
    document.getElementById('lightboxInfo').textContent = `${p.time}${p.deltaLabel ? ' · ' + p.deltaLabel : ''}`;
    document.getElementById('lightboxCount').textContent = `${lightboxIndex + 1} / ${lightboxPhotos.length}`;
}

export function openLightbox() {
    if (lightboxPhotos.length > 0) openLightboxAt(lightboxPhotos.length - 1);
}

export function openLightboxAt(idx) {
    lightboxIndex = Math.max(0, Math.min(idx, lightboxPhotos.length - 1));
    showCurrentLightbox();
    document.getElementById('lightbox').classList.add('open');
}

export function openLightboxSrc(src) {
    const idx = lightboxPhotos.findIndex(p => p.url === src);
    openLightboxAt(idx >= 0 ? idx : 0);
}

export function lightboxNav(dir) {
    if (!lightboxPhotos.length) return;
    lightboxIndex = (lightboxIndex + dir + lightboxPhotos.length) % lightboxPhotos.length;
    showCurrentLightbox();
}

export function closeLightbox() {
    document.getElementById('lightbox').classList.remove('open');
}

export function updateLatestPhoto(latest) {
    const frame = document.getElementById('photoFrame');
    const timeEl = document.getElementById('photoTime');

    if (!latest || !latest.foto_url) {
        if (frame) frame.innerHTML = '<span class="placeholder">📷</span>';
        if (timeEl) timeEl.textContent = '';
        return;
    }

    if (frame) {
        const fallbackStr = latest.foto_drive_id ? `this.onerror=null; this.src='https://drive.google.com/uc?id=${latest.foto_drive_id}';` : `this.parentElement.innerHTML='<span class=placeholder>📷</span>'`;
        frame.innerHTML = `<img src="${latest.foto_url}" alt="Latest capture" onerror="${fallbackStr}">`;
    }

    if (latest.timestamp && timeEl) {
        const t = new Date(latest.timestamp);
        timeEl.textContent = t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
}

function forceDownload(url, filename) {
    // Bypass CORS blocked BLOB fetch completely by instructing window to open purely natively
    const nativeDownloadAnchor = document.createElement('a');
    nativeDownloadAnchor.href = url + '&confirm=t'; // Attempt force direct download
    nativeDownloadAnchor.target = '_blank';
    nativeDownloadAnchor.download = filename;
    document.body.appendChild(nativeDownloadAnchor);
    nativeDownloadAnchor.click();
    document.body.removeChild(nativeDownloadAnchor);
}

// Expose forceDownload globally for onclick in gallery HTML
window.forceDownload = forceDownload;

export function updateGallery(measurements, gd, session) {
    const grid = document.getElementById('galleryGrid');
    const withPhotos = measurements.filter(m => m.foto_url);

    if (!withPhotos.length) {
        grid.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:20px">Sin fotos aun — las capturas nuevas apareceran aqui</div>';
        lightboxPhotos = [];
        return;
    }

    // Build lightbox data (ascending order for nav)
    lightboxPhotos = withPhotos.map((m, idx) => {
        const t = new Date(m.timestamp);
        const time = t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
        let deltaLabel = '';

        if (idx === 0) {
            // First photo = baseline, no previous to compare
            deltaLabel = '+0%';
        } else {
            // Scan backwards for the nearest previous photo with nivel_pct
            let prevIdx = idx - 1;
            while (prevIdx >= 0 && withPhotos[prevIdx].nivel_pct == null) prevIdx--;
            const prev = prevIdx >= 0 ? withPhotos[prevIdx] : null;

            if (prev && m.nivel_pct != null && gd) {
                const mIdx = gd.validMeds.indexOf(m);
                const prevIdxInGd = gd.validMeds.indexOf(prev);
                if (mIdx !== -1 && prevIdxInGd !== -1) {
                    const delta = gd.growthArr[mIdx] - gd.growthArr[prevIdxInGd];
                    deltaLabel = (delta >= 0 ? '+' : '') + delta.toFixed(1) + '%';
                }
            }
        }

        return { url: m.foto_url, driveId: m.foto_drive_id, time, deltaLabel };
    });

    // Show newest first in the grid
    const total = lightboxPhotos.length;
    const photosHtml = [...lightboxPhotos].reverse().map((p, descIdx) => {
        const ascIdx = total - 1 - descIdx;
        const fallbackStr = p.driveId ? `this.onerror=null; this.src='https://drive.google.com/uc?id=${p.driveId}';` : `this.parentElement.style.display='none'`;
        return `<div class="gallery-thumb" onclick="openLightboxAt(${ascIdx})">
            <img src="${p.url}" alt="${p.time}" loading="lazy" onerror="${fallbackStr}">
            <div class="gallery-label" style="justify-content:center;">
                <span class="gl-time">${p.time}</span>
            </div>
        </div>`;
    }).join('');

    // Add Timelapse Card at the beginning if a URL exists
    const timelapseUrl = session ? session.timelapse_url : null;
    const timelapseHtml = (timelapseUrl && lightboxPhotos.length > 1) ? `
        <div class="gallery-thumb" style="border: 2px solid var(--accent-primary); position: relative; cursor: pointer; overflow: hidden; background-color: #111;" onclick="forceDownload('${timelapseUrl}', 'timelapse_fermento.mp4')" title="Clic para descargar MP4">
            <img src="${lightboxPhotos[lightboxPhotos.length-1].url}" style="width: 100%; height: 100%; object-fit: cover; opacity: 0.5; filter: blur(2px);">
            <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; flex-direction: column;">
                <div style="font-size: 24px; margin-bottom: 4px;">🎬</div>
                <div style="font-size: 11px; font-weight: bold; color: white;">Descargar<br>MP4</div>
            </div>
        </div>
    ` : '';

    grid.innerHTML = timelapseHtml + photosHtml;
}

// ─── Keyboard navigation for lightbox ───
export function setupLightboxKeyboard(getIsCalibrating) {
    document.addEventListener('keydown', e => {
        const lb = document.getElementById('lightbox');
        if (!lb.classList.contains('open')) return;
        if (e.key === 'Escape')      closeLightbox();
        else if (e.key === 'ArrowRight' && !getIsCalibrating()) lightboxNav(1);
        else if (e.key === 'ArrowLeft' && !getIsCalibrating())  lightboxNav(-1);
    });
}
