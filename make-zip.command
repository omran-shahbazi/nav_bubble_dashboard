#!/bin/bash
# Double-click this file in Finder to make a zip of the dashboard to send to someone.
# The zip leaves out .venv (installed packages, ~400 MB): run.command reinstalls them on the other Mac.
# It also leaves out .git (the repository history).

cd "$(dirname "$0")/.." || exit 1
NAME="$(basename "$(dirname "$0")")"
ZIP="$PWD/$NAME-$(date +%Y-%m-%d).zip"

rm -f "$ZIP"
zip -r -q "$ZIP" "$NAME" -x "$NAME/.venv/*" "$NAME/.git/*" "*/__pycache__/*" "*.DS_Store" "*.tmp" "*.Rhistory" || {
    echo "Could not make the zip (see the messages above)."
    read -r -p "Press Enter to close."
    exit 1
}

echo "Made $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "Send this file. The other person unzips it and double-clicks run.command inside."
open -R "$ZIP"   # show it in Finder
