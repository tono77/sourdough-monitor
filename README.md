# 🍞 Sourdough Starter Monitor

Automated monitoring system for sourdough fermentation using computer vision, Claude AI, and real-time analytics.

## Features

✅ **Automated Photo Capture** — Every 5 minutes via ffmpeg + launchd daemon  
✅ **Claude Haiku Vision Analysis** — Fermentation level, bubble activity, texture assessment  
✅ **SQLite Database** — All measurements stored locally  
✅ **Dark Mode Graphs** — Real-time visualization of fermentation progress  
✅ **Peak Detection** — Automatically identifies fermentation peak (first descent)  
✅ **WhatsApp Integration** — Hourly updates with photos + graphs  
✅ **Cost Optimized** — Uses Haiku ($0.10-0.25/fermentation) vs Sonnet ($0.50-1.20)  

## Architecture

```
📸 ffmpeg daemon (every 5 min)
    ↓
💾 Latest photo → photos/latest.jpg
    ↓
⏰ Cron Job #1 (every 30 min)
    ├─ analyze.py (Claude Haiku vision)
    ├─ chart.py (matplotlib graphs)
    └─ SQLite updates
    ↓
📤 Cron Job #2 (30 min + 1 sec)
    └─ WhatsApp delivery (photo + graph)
```

## Setup

### Prerequisites
- macOS with camera (FaceTime HD or external)
- Python 3.9+
- ffmpeg with AVFoundation support
- Claude API key

### Installation

```bash
# Clone repo
git clone https://github.com/tono77/sourdough-monitor.git
cd sourdough-monitor

# Create directories
mkdir -p data photos charts

# Install Python deps
pip3 install anthropic matplotlib requests

# Initialize SQLite database
python3 -c "
import sqlite3
conn = sqlite3.connect('data/fermento.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS mediciones (
  id INTEGER PRIMARY KEY,
  timestamp TEXT,
  foto_path TEXT,
  nivel_pct REAL,
  nivel_px INTEGER,
  burbujas TEXT,
  textura TEXT,
  notas TEXT,
  es_peak INTEGER
)
''')
conn.commit()
"

# Start capture daemon
launchctl load ~/Library/LaunchAgents/com.sourdough.capture.plist
```

### Configuration

Edit `capture_daemon.sh` to change:
- Camera device (default: `0` = FaceTime HD)
- Capture interval (default: 300 seconds = 5 min)

Edit OpenClaw cron jobs:
- **Job 1:** Analysis every 30 min
- **Job 2:** WhatsApp delivery 1 min later

### API Keys

Set environment variable:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Usage

### Manual Capture & Analysis

```bash
# Capture single photo
bash capture.sh

# Analyze latest photo
python3 analyze.py photos/latest.jpg

# Generate graph
python3 chart.py
```

### View Database

```bash
sqlite3 data/fermento.db "SELECT * FROM mediciones"
```

### Check Daemon Status

```bash
launchctl list | grep sourdough
tail -f data/daemon.log
```

## Metrics Tracked

| Metric | Type | Values |
|--------|------|--------|
| `timestamp` | DateTime | ISO-8601 |
| `nivel_pct` | Float | 0-150 (% vs baseline) |
| `burbujas` | Enum | ninguna/pocas/muchas |
| `textura` | Enum | lisa/rugosa/muy_activa |
| `notas` | String | Claude observations |
| `es_peak` | Bool | Peak detection flag |

## Cost Analysis

**Per fermentation cycle (8-12 hours, ~20-30 captures):**
- Haiku: **$0.10-0.25 USD**
- Sonnet: $0.50-1.20 USD
- **Monthly (3 ferments): ~$0.75-1.00 USD**

## Peak Detection

Triggered when:
1. Level starts descending (first drop after maximum)
2. Bubble activity remains high (muchas)
3. Flag set in database for historical tracking

## Troubleshooting

### Camera Permission Denied
```bash
sudo tccutil reset Camera
# Re-run ffmpeg, accept permission dialog
```

### Daemon Not Starting
```bash
launchctl unload ~/Library/LaunchAgents/com.sourdough.capture.plist
launchctl load ~/Library/LaunchAgents/com.sourdough.capture.plist
```

### Graph Not Generating
```bash
python3 chart.py  # Check for errors
# Verify matplotlib installed: pip3 show matplotlib
```

## Files

```
sourdough-monitor/
├── analyze.py              # Claude Haiku vision analysis
├── chart.py               # matplotlib graph generation
├── capture.sh             # ffmpeg wrapper
├── capture_daemon.sh      # launchd daemon script
├── README.md
├── data/
│   ├── fermento.db        # SQLite database
│   ├── sourdough.log      # Application log
│   └── daemon.log         # Capture daemon log
├── photos/
│   ├── fermento_*.jpg     # Individual captures
│   └── latest.jpg         # Symlink to newest
└── charts/
    └── sourdough_*.png    # Daily graphs (dark mode)
```

## Integration: OpenClaw

This project runs on **OpenClaw** with two scheduled crons:

1. **Analysis Cron** — Isolated session, every 30 min
   - Reads `photos/latest.jpg` (from daemon)
   - Calls Claude Haiku for vision analysis
   - Generates matplotlib graph
   - Updates SQLite

2. **Delivery Cron** — Main session, 1 min after analysis
   - Sends photo + metrics to WhatsApp
   - Sends graph PNG
   - Alert on peak detection

## Future Enhancements

- [ ] Multi-camera support
- [ ] Temperature sensor integration
- [ ] Humidity logging
- [ ] Community leaderboard (fermentation times)
- [ ] Mobile app for remote monitoring
- [ ] Predictive peak timing (ML model)

## License

MIT — Feel free to fork, modify, and improve!

## Author

Built by **Anatoly** 🤖 for Ed Ochoa @ STATION 2.0 / Finvivir  
Inspired by sourdough science + cost optimization 🍞

---

**Questions?** File an issue or DM @edgardo.ochoa on Twitter
