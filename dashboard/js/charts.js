// ─── Charts module ───
// Manages Chart.js initialization and updates

let levelChart = null;
let incrementChart = null;
let activityChart = null;

const verticalLinePlugin = {
    id: 'verticalLine',
    beforeDraw: (chart) => {
        const ctx = chart.ctx;
        const xAxis = chart.scales.x;
        const yAxis = chart.scales.y;

        if (chart.config.data.cicloTimestamps) {
            ctx.save();
            ctx.strokeStyle = 'rgba(255, 152,  0, 0.5)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([5, 5]);

            chart.config.data.cicloTimestamps.forEach(ts => {
                const x = xAxis.getPixelForValue(new Date(ts));
                if (x >= xAxis.left && x <= xAxis.right) {
                    ctx.beginPath();
                    ctx.moveTo(x, yAxis.top);
                    ctx.lineTo(x, yAxis.bottom);
                    ctx.stroke();
                }
            });
            ctx.restore();
        }
    }
};

let onPointClick = null;

export function setOnPointClick(callback) {
    onPointClick = callback;
}

export function initCharts() {
    if (levelChart) return; // already initialized

    Chart.defaults.color = '#888';
    Chart.defaults.borderColor = 'rgba(255,255,255,0.05)';
    Chart.defaults.font.family = "'Inter', sans-serif";

    const levelCtx = document.getElementById('levelChart').getContext('2d');
    levelChart = new Chart(levelCtx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Nivel (%)',
                data: [],
                borderColor: '#e94560',
                backgroundColor: 'rgba(233,69,96,0.08)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointBackgroundColor: '#e94560',
                pointBorderColor: '#0c0c24',
                pointBorderWidth: 2,
                pointHoverRadius: 6,
            }, {
                label: 'Peak',
                data: [],
                borderColor: 'transparent',
                backgroundColor: '#ffd700',
                pointRadius: 10,
                pointStyle: 'star',
                showLine: false,
            }, {
                label: 'Meta Duplicacion (100%)',
                data: [],
                borderColor: 'rgba(76, 175, 80, 0.8)',
                borderWidth: 2,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            onClick: (event, elements) => {
                if (!elements.length || !onPointClick) return;
                const el = elements[0];
                if (el.datasetIndex !== 0) return; // only main level dataset
                const point = levelChart.data.datasets[0].data[el.index];
                if (point) onPointClick(point);
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(12,12,36,0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    titleFont: { weight: '600' },
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: ctx => `Nivel: ${ctx.parsed.y?.toFixed(1) ?? '--'}%`
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm', minute: 'HH:mm' } },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { maxRotation: 0 }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    title: { display: true, text: 'Crecimiento desde inicio (%)', color: '#666' },
                    ticks: { callback: v => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%` },
                    suggestedMin: -5,
                    suggestedMax: 10
                }
            }
        },
        plugins: [verticalLinePlugin]
    });

    const incCtx = document.getElementById('incrementChart').getContext('2d');
    incrementChart = new Chart(incCtx, {
        type: 'bar',
        data: {
            datasets: [{
                label: 'Avance vs Anterior (%)',
                data: [],
                backgroundColor: (ctx) => {
                    const val = ctx.raw ? ctx.raw.y : 0;
                    return val > 0 ? 'rgba(76, 175, 80, 0.85)' : (val < 0 ? 'rgba(233, 69, 96, 0.85)' : 'rgba(255, 255, 255, 0.3)');
                },
                borderColor: (ctx) => {
                    const val = ctx.raw ? ctx.raw.y : 0;
                    return val > 0 ? '#66bb6a' : (val < 0 ? '#ef5350' : 'rgba(255, 255, 255, 0.5)');
                },
                borderWidth: 2,
                borderRadius: 4,
                minBarLength: 6,
                barThickness: 'flex',
                maxBarThickness: 20
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(12,12,36,0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: ctx => {
                            const val = ctx.parsed.y;
                            const sign = val > 0 ? '+' : '';
                            return `Incremento: ${sign}${val.toFixed(1)}%`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                    grid: { color: 'rgba(255,255,255,0.08)' },
                    ticks: { maxRotation: 0, color: '#888' }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.08)' },
                    title: { display: true, text: 'Avance %', color: '#aaa', font: { size: 11 } },
                    ticks: { color: '#888', callback: v => `${v >= 0 ? '+' : ''}${v}%` },
                    suggestedMin: -3,
                    suggestedMax: 3
                }
            }
        },
        plugins: [verticalLinePlugin]
    });

    const actCtx = document.getElementById('activityChart').getContext('2d');
    activityChart = new Chart(actCtx, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Burbujas',
                data: [],
                borderColor: '#e8a045',
                backgroundColor: 'rgba(232,160,69,0.1)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#e8a045',
                pointBorderColor: '#0c0c24',
                pointBorderWidth: 2,
            },
            {
                label: 'Meta Duplicacion (100%)',
                data: [],
                borderColor: 'rgba(76, 175, 80, 0.8)',
                borderWidth: 2,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(12,12,36,0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: ctx => {
                            const labels = ['Ninguna', 'Pocas', 'Muchas'];
                            return `Burbujas: ${labels[ctx.parsed.y] || '--'}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { maxRotation: 0 }
                },
                y: {
                    min: -0.2, max: 2.5,
                    ticks: {
                        stepSize: 1,
                        callback: v => ['Ninguna', 'Pocas', 'Muchas'][v] || ''
                    },
                    grid: { color: 'rgba(255,255,255,0.03)' }
                }
            }
        },
        plugins: [verticalLinePlugin]
    });
}

export function updateCharts(measurements, gd, session) {
    if (!levelChart || !gd) return;
    const { validMeds, growthArr } = gd;
    const bubbleMap = { 'ninguna': 0, 'pocas': 1, 'muchas': 2 };

    // Set X-axis window based on GLOBAL session start time (guarantee min 24h span)
    if (session && session.hora_inicio) {
        const startTime = new Date(session.hora_inicio).getTime();

        let latestTime = startTime;
        if (measurements.length > 0) {
            latestTime = new Date(measurements[measurements.length - 1].timestamp).getTime();
        }
        // Stretch the chart bounds if fermentation breaches the first 24 hours
        const endTime = Math.max(startTime + (24 * 60 * 60 * 1000), latestTime + (1 * 60 * 60 * 1000));

        levelChart.options.scales.x.min = startTime;
        levelChart.options.scales.x.max = endTime;
        activityChart.options.scales.x.min = startTime;
        activityChart.options.scales.x.max = endTime;
    }

    levelChart.data.datasets[0].data = validMeds.map((m, i) => ({
        x: new Date(m.timestamp), y: growthArr[i],
        _id: m._id, foto_url: m.foto_url, foto_drive_id: m.foto_drive_id,
        timestamp: m.timestamp, burbujas: m.burbujas, textura: m.textura,
        notas: m.notas, nivel_pct: m.nivel_pct, crecimiento_pct: m.crecimiento_pct
    }));

    // Pass cycle event timestamps back to plugin
    const cicloEvents = measurements.filter(m => m.is_ciclo === true);
    levelChart.data.cicloTimestamps = cicloEvents.map(m => m.timestamp);
    activityChart.data.cicloTimestamps = cicloEvents.map(m => m.timestamp);

    // Peak marker: only show if it's the actual latest maximum
    const latestGrowth = growthArr[growthArr.length - 1];
    levelChart.data.datasets[1].data = validMeds
        .map((m, i) => ({ m, i }))
        .filter(({ m, i }) => {
            if (!(m.es_peak === 1 || m.es_peak === true)) return false;
            return growthArr[i] >= latestGrowth - 2; // only confirmed peaks
        })
        .map(({ m, i }) => ({ x: new Date(m.timestamp), y: growthArr[i] }));

    levelChart.data.datasets[2].data = validMeds.map(m => ({
        x: new Date(m.timestamp), y: 100
    }));
    levelChart.update('none');

    activityChart.data.datasets[0].data = measurements.map(m => ({
        x: new Date(m.timestamp),
        y: bubbleMap[m.burbujas] ?? 0
    }));
    activityChart.update('none');

    // Build increment data — skip first point and cycle boundaries
    const cicloTimestampSet = new Set(cicloEvents.map(m => m.timestamp));
    const incrementData = [];
    for (let i = 1; i < validMeds.length; i++) {
        // Skip if this is the first measurement after a cycle reset
        // (detected when the previous measurement's timestamp is before a ciclo event
        //  that sits between prev and current)
        const prevTime = new Date(validMeds[i - 1].timestamp).getTime();
        const currTime = new Date(validMeds[i].timestamp).getTime();
        const crossesCycle = cicloEvents.some(c => {
            const ct = new Date(c.timestamp).getTime();
            return ct > prevTime && ct <= currTime;
        });
        if (crossesCycle) continue;

        const delta = growthArr[i] - growthArr[i - 1];
        incrementData.push({
            x: new Date(validMeds[i].timestamp),
            y: Math.round(delta * 10) / 10
        });
    }
    incrementChart.data.datasets[0].data = incrementData;

    if (session && session.hora_inicio) {
        const startTime = new Date(session.hora_inicio).getTime();
        const latestTime = measurements.length > 0 ? new Date(measurements[measurements.length - 1].timestamp).getTime() : startTime;
        const endTime = Math.max(startTime + (24 * 60 * 60 * 1000), latestTime + (1 * 60 * 60 * 1000));

        incrementChart.options.scales.x.min = startTime;
        incrementChart.options.scales.x.max = endTime;
    }
    incrementChart.data.cicloTimestamps = cicloEvents.map(m => m.timestamp);
    incrementChart.update('none');
}
