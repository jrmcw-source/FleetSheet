#!/bin/sh
cd "$(dirname "$0")"
if ! python3 -c "import reportlab" 2>/dev/null; then
  echo "Note: reportlab not found. On-screen print still works. PDF file download needs: pip install reportlab"
fi
exec python3 app.py
