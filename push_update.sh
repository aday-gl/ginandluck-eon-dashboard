#!/bin/bash
# Run this from Terminal to commit and push the latest dashboard update to GitHub.
# Usage: bash push_update.sh

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "→ Removing stale lock file if present..."
rm -f .git/index.lock

echo "→ Staging files..."
git add EON_Dashboard.html index.html generate_eon_dashboard.py eon_data/ 2026_budgets/

echo "→ Committing..."
git commit -m "EON Dashboard — R365 backfill + MTD pace indicators ($(date '+%Y-%m-%d'))" \
  || echo "(Nothing new to commit)"

echo "→ Pushing to GitHub..."
git push origin main

echo ""
echo "✓ Done! Live dashboard: https://aday-gl.github.io/ginandluck-eon-dashboard/EON_Dashboard.html"
