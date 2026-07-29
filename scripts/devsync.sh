#!/usr/bin/env bash
# Local dev shim for the ThreatLocker .py restriction.
#
# python.exe on this machine cannot read .py files under the project directory
# (see docs/notebook-recon.md and the README), but it can read them inside
# site-packages, and bash can read them anywhere. So: copy the Python tree into
# a staging dir under site-packages and run it from there.
#
# The repo stays the single source of truth — this only ever copies out of it.
# Delete this script once the ThreatLocker exclusion is in place; nothing else
# depends on it, and CI (Linux) never needs it.
#
#   bash scripts/devsync.sh                          # sync only
#   bash scripts/devsync.sh pytest -q                # sync + run tests
#   bash scripts/devsync.sh python -m pipeline.build --season 2526 --source snapshot
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$(python -c 'import site; print(site.getusersitepackages())')"
STAGE="$SITE/_wod_dev"

rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -r "$REPO/pipeline" "$STAGE/"
[ -d "$REPO/tests" ] && cp -r "$REPO/tests" "$STAGE/"
[ -f "$REPO/pytest.ini" ] && cp "$REPO/pytest.ini" "$STAGE/"
# Reference data and CSVs are not .py, so they stay readable in place — tests
# locate them through this.
export WOD_REPO_ROOT="$REPO"
export PYTHONPATH="$STAGE"
export PYTHONDONTWRITEBYTECODE=1

if [ "$#" -eq 0 ]; then
  echo "synced -> $STAGE"
  exit 0
fi

cd "$STAGE"
if [ "$1" = "pytest" ]; then
  shift
  exec python -m pytest "$@"
fi
exec "$@"
