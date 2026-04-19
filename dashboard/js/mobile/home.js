const TEX_LABEL = { lisa: 'lisa', rugosa: 'rugosa', muy_activa: 'muy activa' };
const BUB_LABEL = { ninguna: 'ninguna', pocas: 'pocas', muchas: 'muchas' };

export function setPeakMode(on) {
  document.documentElement.dataset.peak = on ? '1' : '0';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', on ? '#0a2b11' : '#0a0a0a');
  document.getElementById('mStatusBand').classList.toggle('peak', on);
}

export function renderHome({ session, measurements, isHibernating }) {
  const meds = measurements.filter(m => !m.is_ciclo);
  const latest = meds.length ? meds[meds.length - 1] : null;
  const prev = meds.length > 1 ? meds[meds.length - 2] : null;

  const currentPct = pickPct(latest);
  const prevPct = pickPct(prev);
  const deltaPct = currentPct != null && prevPct != null ? currentPct - prevPct : null;

  renderToolbar(session, latest, currentPct, deltaPct);
  renderStatusBand(session, meds, isHibernating);
  renderPhoto(latest);
  renderSparkline(meds);
  renderStats(latest, meds);
  renderTimeline(measurements);
  renderFab(measurements);

  document.getElementById('mBtnRefrigerar').setAttribute('aria-pressed', isHibernating ? 'true' : 'false');
  document.getElementById('mBtnRefrigerar').textContent = isHibernating ? '🌞' : '❄';
}

function pickPct(m) {
  if (!m) return null;
  if (m.altura_pct != null) return parseFloat(m.altura_pct);
  if (m.nivel_pct != null) return parseFloat(m.nivel_pct);
  return null;
}

function fmtElapsed(startIso, nowMs) {
  if (!startIso) return '--:--';
  const ms = Math.max(0, nowMs - new Date(startIso).getTime());
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

function renderToolbar(session, latest, currentPct, deltaPct) {
  const now = Date.now();
  const elapsed = fmtElapsed(session.hora_inicio, now);
  const cycleLabel = (session.fecha || 'SESIÓN').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim();
  document.getElementById('mCycleLabel').textContent = `${cycleLabel} · T+${elapsed}`;

  document.getElementById('mHeroNum').textContent = currentPct != null ? Math.round(currentPct) : '--';
  const deltaEl = document.getElementById('mHeroDelta');
  if (deltaPct == null || Math.abs(deltaPct) < 0.5) {
    deltaEl.textContent = '';
  } else {
    const arrow = deltaPct > 0 ? '▲' : '▼';
    deltaEl.textContent = `${arrow} ${Math.abs(deltaPct).toFixed(0)}%`;
  }
}

function renderStatusBand(session, meds, isHibernating) {
  const band = document.getElementById('mStatusBand');
  const text = document.getElementById('mStatusText');
  const eta = document.getElementById('mStatusEta');

  band.classList.remove('peak', 'warn');

  if (isHibernating) {
    band.classList.add('warn');
    text.textContent = '❄ REFRIGERANDO · MONITOR PAUSADO';
    eta.textContent = '';
    return;
  }
  if (!session || session.estado !== 'activa') {
    text.textContent = '● SESIÓN COMPLETADA';
    eta.textContent = meds.length ? `${meds.length} MED.` : '';
    return;
  }
  if (session.ventana_pan_activa) {
    band.classList.add('peak');
    text.textContent = '🎯 PEAK · VENTANA ABIERTA';
    eta.textContent = 'HORA DE HORNEAR';
    return;
  }
  const latestPct = pickPct(meds[meds.length - 1]);
  if (latestPct != null) {
    text.textContent = `● FERMENTANDO · ${Math.round(latestPct)}% ALTURA`;
  } else {
    text.textContent = '● ESPERANDO MEDICIÓN';
  }
  eta.textContent = estimateEta(meds);
}

function estimateEta(meds) {
  const recent = meds.slice(-6);
  if (recent.length < 3) return '';
  const a = recent[0], b = recent[recent.length - 1];
  const ay = pickPct(a), by = pickPct(b);
  if (ay == null || by == null) return '';
  const dtH = (new Date(b.timestamp) - new Date(a.timestamp)) / 3600000;
  if (dtH <= 0) return '';
  const rate = (by - ay) / dtH;
  if (rate <= 2) return '';
  const toTarget = 90 - by;
  if (toTarget <= 0) return '';
  const etaMin = Math.round((toTarget / rate) * 60);
  if (etaMin < 5 || etaMin > 600) return '';
  return `ETA ~${etaMin}MIN`;
}

function renderPhoto(latest) {
  const frame = document.getElementById('mPhotoFrame');
  const tag = document.getElementById('mPhotoTag');

  const src = latest && (latest.foto_url
    || (latest.foto_drive_id ? `https://drive.google.com/uc?id=${latest.foto_drive_id}` : null));

  if (src) {
    let img = frame.querySelector('img');
    if (!img) {
      frame.innerHTML = '';
      img = document.createElement('img');
      img.alt = 'Última captura';
      img.loading = 'eager';
      frame.appendChild(img);
    }
    if (img.getAttribute('data-src') !== src) {
      img.setAttribute('data-src', src);
      img.src = src;
    }
  } else {
    frame.innerHTML = '<div class="m-photo-placeholder">📷</div>';
  }

  if (latest && latest.timestamp) {
    const t = new Date(latest.timestamp);
    tag.textContent = `ÚLTIMA · ${t.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}`;
    tag.style.display = '';
  } else {
    tag.style.display = 'none';
  }
}

function renderSparkline(meds) {
  const host = document.getElementById('mSpark');
  const pts = meds.map(m => pickPct(m)).filter(v => v != null);
  document.getElementById('mCurveMeta').textContent = `${pts.length} PTS`;

  if (pts.length < 2) {
    host.innerHTML = '<svg viewBox="0 0 370 70" preserveAspectRatio="none"></svg>';
    return;
  }

  const w = 370, h = 70, pad = 2;
  const max = 100;
  const coords = pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * w;
    const y = h - (Math.max(0, Math.min(max, v)) / max) * (h - 2 * pad) - pad;
    return [x, y];
  });
  const d = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const dFill = `${d} L${w},${h} L0,${h} Z`;
  const grid = 'rgba(255,255,255,0.06)';
  const gridLines = [0, 25, 50, 75, 100].map(p => {
    const y = h - (p / 100) * (h - 2 * pad) - pad;
    return `<line x1="0" y1="${y.toFixed(1)}" x2="${w}" y2="${y.toFixed(1)}" stroke="${grid}" stroke-width="0.5"/>`;
  }).join('');
  const targetY = h - (90 / 100) * (h - 2 * pad) - pad;
  const [lx, ly] = coords[coords.length - 1];

  host.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-label="Curva de crecimiento">
      ${gridLines}
      <line x1="0" y1="${targetY.toFixed(1)}" x2="${w}" y2="${targetY.toFixed(1)}" stroke="var(--m-accent)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.5"/>
      <path d="${dFill}" fill="var(--m-accent)" opacity="0.12"/>
      <path d="${d}" fill="none" stroke="var(--m-accent)" stroke-width="1.5"/>
      <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3" fill="var(--m-accent)"/>
    </svg>`;
}

function renderStats(latest, meds) {
  const bubEl = document.getElementById('mStatBubbles');
  const texEl = document.getElementById('mStatTexture');
  const velEl = document.getElementById('mStatVel');

  bubEl.textContent = latest && latest.burbujas ? (BUB_LABEL[latest.burbujas] || latest.burbujas) : '—';
  texEl.textContent = latest && latest.textura ? (TEX_LABEL[latest.textura] || latest.textura) : '—';
  velEl.textContent = computeVelocity(meds);
}

function computeVelocity(meds) {
  const recent = meds.slice(-4);
  if (recent.length < 2) return '—';
  const a = recent[0], b = recent[recent.length - 1];
  const ay = pickPct(a), by = pickPct(b);
  if (ay == null || by == null) return '—';
  const dtH = (new Date(b.timestamp) - new Date(a.timestamp)) / 3600000;
  if (dtH <= 0) return '—';
  const rate = (by - ay) / dtH;
  const sign = rate > 0 ? '+' : '';
  return `${sign}${rate.toFixed(0)}%/h`;
}

function renderTimeline(measurements) {
  const list = document.getElementById('mTimeline');
  const meta = document.getElementById('mTimelineMeta');

  const display = [...measurements].reverse();
  const pending = measurements.filter(m => !m.is_ciclo && !m.is_manual_override).length;
  meta.textContent = `${pending} PENDIENTE${pending !== 1 ? 'S' : ''}`;

  if (!display.length) {
    list.innerHTML = '<div class="m-tl-empty">SIN MEDICIONES</div>';
    return;
  }

  const latestId = display.find(m => !m.is_ciclo)?._id;
  list.innerHTML = display.map(m => {
    const t = m.timestamp ? new Date(m.timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' }) : '--:--';
    if (m.is_ciclo) {
      const note = (m.notas || '🔄 Nuevo ciclo').replace(/^🔄\s*/, '');
      return `
        <button class="m-tl-row" data-ciclo="1" data-id="${m._id}" type="button">
          <span class="m-tl-dot" data-state="ciclo"></span>
          <span class="m-tl-time">${t}</span>
          <span class="m-tl-desc">${escapeHtml(note)}</span>
          <span class="m-tl-pct">—</span>
        </button>`;
    }
    const isLatest = m._id === latestId;
    const calibrated = !!m.is_manual_override;
    const state = isLatest ? 'latest' : (calibrated ? 'calibrated' : 'pending');
    const pct = pickPct(m);
    const bub = m.burbujas ? (BUB_LABEL[m.burbujas] || m.burbujas) : '—';
    const tex = m.textura ? (TEX_LABEL[m.textura] || m.textura) : '—';
    const warn = calibrated ? '' : '<span class="m-tl-warn">● SIN CALIBRAR</span>';
    return `
      <button class="m-tl-row" data-id="${m._id}" type="button">
        <span class="m-tl-dot" data-state="${state}"></span>
        <span class="m-tl-time">${t}</span>
        <span class="m-tl-desc">${escapeHtml(bub)} · ${escapeHtml(tex)}${warn}</span>
        <span class="m-tl-pct" data-state="${state}">${pct != null ? Math.round(pct) : '—'}%</span>
      </button>`;
  }).join('');

  list.onclick = (e) => {
    const row = e.target.closest('.m-tl-row');
    if (!row || row.dataset.ciclo === '1') return;
    const id = row.dataset.id;
    const m = measurements.find(x => x._id === id);
    if (!m) return;
    const ev = new CustomEvent('m-tl-click', { detail: { measurement: m } });
    document.dispatchEvent(ev);
  };
}

function renderFab(measurements) {
  const pending = measurements.filter(m => !m.is_ciclo && !m.is_manual_override).length;
  const badge = document.getElementById('mFabBadge');
  if (pending > 0) {
    badge.hidden = false;
    badge.textContent = String(pending);
  } else {
    badge.hidden = true;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
