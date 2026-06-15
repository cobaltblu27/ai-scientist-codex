#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Usage: ./install.sh [--python-runtime COMMAND] [--venv-dir PATH] [--bin-dir PATH]

Options:
  --python-runtime COMMAND  Python command used to create/update the venv.
                            Default: reuse existing venv Python when present,
                            then the remembered runtime, then python3.
                            Examples: python3.12, /opt/homebrew/bin/python3.12,
                            "conda run -n base python"
  --venv-dir PATH           Venv directory. Default: <repo>/.venv-ai-scientist
  --bin-dir PATH            Directory for ai-scientist launcher. Default: ~/.local/bin
Environment:
  AI_SCIENTIST_PLUGIN_CACHE Optional Codex plugin cache directory to refresh.
                            Default: ~/.codex/plugins/cache/ai-scientist-codex/ai-scientist/0.1.2
  -h, --help                Show this help.
EOF
}

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_RUNTIME="${AI_SCIENTIST_PYTHON:-}"
PYTHON_RUNTIME_EXPLICIT=0
VENV_DIR="$ROOT/.venv-ai-scientist"
BIN_DIR="$HOME/.local/bin"
PLUGIN_CACHE_DIR="${AI_SCIENTIST_PLUGIN_CACHE:-$HOME/.codex/plugins/cache/ai-scientist-codex/ai-scientist/0.1.2}"
CACHE_BACKUP_ROOT="$HOME/.codex/tmp/plugin-cache-backups"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --python-runtime)
      [ "$#" -ge 2 ] || { echo "missing value for --python-runtime" >&2; exit 2; }
      PYTHON_RUNTIME="$2"
      PYTHON_RUNTIME_EXPLICIT=1
      shift 2
      ;;
    --venv-dir)
      [ "$#" -ge 2 ] || { echo "missing value for --venv-dir" >&2; exit 2; }
      VENV_DIR="$2"
      shift 2
      ;;
    --bin-dir)
      [ "$#" -ge 2 ] || { echo "missing value for --bin-dir" >&2; exit 2; }
      BIN_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

run_python() {
  sh -c "$PYTHON_RUNTIME \"\$@\"" sh "$@"
}

runtime_record_path() {
  printf '%s\n' "$VENV_DIR/.ai-scientist-python-runtime"
}

if [ "$PYTHON_RUNTIME_EXPLICIT" -eq 0 ] && [ -x "$VENV_DIR/bin/python" ]; then
  PYTHON_RUNTIME="$VENV_DIR/bin/python"
elif [ "$PYTHON_RUNTIME_EXPLICIT" -eq 0 ] && [ -f "$(runtime_record_path)" ]; then
  PYTHON_RUNTIME="$(cat "$(runtime_record_path)")"
elif [ -z "$PYTHON_RUNTIME" ]; then
  PYTHON_RUNTIME="python3"
fi

if ! run_python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  cat >&2 <<EOF
Blocker: Python runtime is missing or older than 3.12.
Evidence: Tried: $PYTHON_RUNTIME
Recommended action: Re-run with --python-runtime "/path/to/python3.12" or --python-runtime "conda run -n base python".
Alternative action: Install Python 3.12+ and re-run install.sh.
Impact: ai-scientist currently declares Python >=3.12 in pyproject.toml.
Question: Proceed with option 1 or 2?
EOF
  exit 1
fi

if [ "$PYTHON_RUNTIME_EXPLICIT" -eq 1 ] || [ ! -x "$VENV_DIR/bin/python" ]; then
  run_python -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade "$ROOT"
printf '%s\n' "$PYTHON_RUNTIME" > "$(runtime_record_path)"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/ai-scientist" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/ai-scientist" "\$@"
EOF
chmod +x "$BIN_DIR/ai-scientist"

CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
"$VENV_DIR/bin/ai-scientist" agents install --codex-home "$CODEX_HOME_DIR" >/dev/null
agents_message="agents:   installed $CODEX_HOME_DIR/agents"

cache_message="plugin cache: not installed; skipped"
if [ -d "$PLUGIN_CACHE_DIR" ]; then
  if ! command -v rsync >/dev/null 2>&1; then
    echo "Blocker: rsync is required to refresh existing Codex plugin cache." >&2
    echo "Evidence: cache exists at $PLUGIN_CACHE_DIR, but rsync was not found on PATH." >&2
    echo "Recommended action: Install rsync, or set AI_SCIENTIST_PLUGIN_CACHE to an empty/nonexistent path to skip cache refresh." >&2
    echo "Alternative action: Manually copy the repository into the plugin cache after backing it up." >&2
    echo "Impact: CLI launcher is installed, but Codex may keep using stale cached skills/prompts." >&2
    echo "Question: Proceed with option 1 or 2?" >&2
    exit 1
  fi
  mkdir -p "$CACHE_BACKUP_ROOT"
  backup_dir="$CACHE_BACKUP_ROOT/0.1.2.bak-$(date +%Y%m%d%H%M%S)"
  cp -a "$PLUGIN_CACHE_DIR" "$backup_dir"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv-ai-scientist/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    "$ROOT/" "$PLUGIN_CACHE_DIR"
  cache_message="plugin cache: refreshed $PLUGIN_CACHE_DIR (backup: $backup_dir)"
fi

cat <<EOF
Installed ai-scientist.
  venv:     $VENV_DIR
  launcher: $BIN_DIR/ai-scientist
  python:   $PYTHON_RUNTIME
  $agents_message
  $cache_message

Make sure $BIN_DIR is on PATH.
EOF
