#!/bin/sh
# Install both halves of ai-scientist from this checkout, at the same version:
#   1. the plugin (skills, agents, prompts) into Claude Code, using this directory as the marketplace
#   2. the `ai-scientist` CLI as a wheel (schemas and the built dashboard bundled) via `uv tool install`
#
# Usage: ./install.sh [--wheel <path-or-url>] [--no-plugin] [--no-dashboard]
#   --wheel         install this wheel instead of building one here (skips the npm build)
#   --no-plugin     CLI only
#   --no-dashboard  skip the frontend build and the claude-agent-sdk extra
# Needs: uv, claude (unless --no-plugin), npm (unless --wheel or --no-dashboard).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
WHEEL=""
PLUGIN=1
DASHBOARD=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --wheel) WHEEL="$2"; shift 2 ;;
    --no-plugin) PLUGIN=0; shift ;;
    --no-dashboard) DASHBOARD=0; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "install.sh: $1 is required on PATH" >&2; exit 1; }; }
need uv
VERSION="$(cd "$ROOT" && uv version --short)"
echo "install.sh: ai-scientist $VERSION from $ROOT"

# --- plugin ---------------------------------------------------------------------------------------
if [ "$PLUGIN" -eq 1 ]; then
  need claude
  source="$(claude plugin marketplace list 2>/dev/null | awk '$2=="ai-scientist"{f=1;next} f&&/Source:/{print;exit}')"
  case "$source" in
    *"($ROOT)"*) claude plugin marketplace update ai-scientist ;;
    "") claude plugin marketplace add "$ROOT" ;;
    *) echo "install.sh: marketplace 'ai-scientist' points elsewhere ($source); re-adding it from this checkout"
       claude plugin marketplace remove ai-scientist
       claude plugin marketplace add "$ROOT" ;;
  esac
  if claude plugin list 2>/dev/null | grep -q 'ai-scientist@ai-scientist'; then
    claude plugin update ai-scientist@ai-scientist
  else
    claude plugin install ai-scientist@ai-scientist
  fi
fi

# --- CLI wheel ------------------------------------------------------------------------------------
if [ -z "$WHEEL" ]; then
  build_dir="$(mktemp -d)"
  trap 'rm -rf "$build_dir"' EXIT
  if [ "$DASHBOARD" -eq 1 ]; then
    need npm
    (cd "$ROOT" && uv run ai-scientist dashboard --build-only >/dev/null)
  fi
  (cd "$ROOT" && uv build --wheel --out-dir "$build_dir" >/dev/null)
  WHEEL="$(ls "$build_dir"/ai_scientist-*.whl)"
fi
if [ "$DASHBOARD" -eq 1 ]; then
  uv tool install --force --python 3.12 "${WHEEL}[dashboard]"
else
  uv tool install --force --python 3.12 "$WHEEL"
fi

bin="$(uv tool dir --bin)"
echo
"$bin/ai-scientist" doctor || true
echo
echo "Installed ai-scientist $VERSION: CLI at $bin/ai-scientist (make sure $bin is on PATH); restart Claude Code to load the plugin."
