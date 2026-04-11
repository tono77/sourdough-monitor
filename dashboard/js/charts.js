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
                    return val > 0 ? 'rgba(76, 175, 80, 0.6)' : (val < 0 ? 'rgba(233, 69, 96, 0.6)' : 'rgba(255, 255, 255, 0.1)');
                },
                borderColor: (ctx) => {
                    const val = ctx.raw ? ctx.raw.y : 0;
                    return val > 0 ? '#4caf50' : (val < 0 ? '#e94560' : 'rgba(255, 255, 255, 0.3)');
                },
                borderWidth: 1,
                borderRadius: 4
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
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { maxRotation: 0 }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    title: { display: true, text: 'Avance %', color: '#888', font: { size: 10 } }
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
        x: new Date(m.timestamp), y: growthArr[i]
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

    // Build increment data
    const incrementData = [];
    for (let i = 0; i < validMeds.length; i++) {
        const prevLevel = i > 0 ? growthArr[i - 1] : 0;
        const currentLevel = growthArr[i];
        incrementData.push({
            x: new Date(validMeds[i].timestamp),
            y: currentLevel - prevLevel
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
