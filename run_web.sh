#!/bin/bash
# Start Canvas Web Dashboard
cd "$(dirname "$0")"
source venv/bin/activate

echo ""
echo "  Canvas Web Dashboard"
echo "  Open: http://localhost:8080"
echo ""

python3 web/app.py
