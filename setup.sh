#!/bin/bash
# Sourdough Monitor — Setup script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🍞 Sourdough Monitor Setup"
echo "=========================="

# Create directories
echo "📁 Creating directories..."
mkdir -p "$SCRIPT_DIR/data" "$SCRIPT_DIR/photos" "$SCRIPT_DIR/charts"

# Create virtual environment
if [ ! -d "$SCRIPT_DIR/venv" ]; then
  echo "🐍 Creating Python virtual environment..."
  python3 -m venv "$SCRIPT_DIR/venv"
fi

# Install dependencies
echo "📦 Installing Python dependencies..."
"$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q

# Initialize database
echo "💾 Initializing database..."
"$SCRIPT_DIR/venv/bin/python3" -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from db import init_db, migrate_historical_data
conn = init_db()
migrate_historical_data(conn)
conn.close()
print('   Database ready')
"

# Make scripts executable
chmod +x "$SCRIPT_DIR/capture.sh" "$SCRIPT_DIR/monitor.py"

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start monitoring:"
echo "  $SCRIPT_DIR/venv/bin/python3 $SCRIPT_DIR/monitor.py"
echo ""
echo "Dashboard only:"
echo "  $SCRIPT_DIR/venv/bin/python3 $SCRIPT_DIR/monitor.py --dashboard"
echo ""
echo "⚠️  Make sure ANTHROPIC_API_KEY is set or ~/.openclaw/config.json exists"
echo ""
echo "📧 To enable email notifications, edit config.json:"
echo "   - Set email.enabled to true"
echo "   - Add your Gmail + app password"
