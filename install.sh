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
  AI_SCIENTIST_PLUGIN_CACHE Optional explicit Codex plugin cache directory to refresh.
                            Default: <codex-home>/plugins/cache/<marketplace>/<plugin>/<manifest-version>
                            The manifest version includes any suffix, such as +codex.<timestamp>.
  -h, --help                Show this help.
EOF
}

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_RUNTIME="${AI_SCIENTIST_PYTHON:-}"
PYTHON_RUNTIME_EXPLICIT=0
VENV_DIR="$ROOT/.venv-ai-scientist"
BIN_DIR="$HOME/.local/bin"
CACHE_BACKUP_ROOT="$HOME/.codex/tmp/plugin-cache-backups"
PLUGIN_MANIFEST="$ROOT/.codex-plugin/plugin.json"
MARKETPLACE_MANIFEST="$ROOT/.agents/plugins/marketplace.json"

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

json_get() {
  "$VENV_DIR/bin/python" -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    value = json.load(f)
for key in sys.argv[2].split("."):
    value = value[key]
print(value)
' "$1" "$2"
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
Tried: $PYTHON_RUNTIME
Re-run with --python-runtime "/path/to/python3.12" or --python-runtime "conda run -n base python".
EOF
  exit 1
fi

if [ "$PYTHON_RUNTIME_EXPLICIT" -eq 1 ] || [ ! -x "$VENV_DIR/bin/python" ]; then
  run_python -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade "$ROOT"
printf '%s\n' "$PYTHON_RUNTIME" > "$(runtime_record_path)"

PLUGIN_NAME="$(json_get "$PLUGIN_MANIFEST" name)"
PLUGIN_VERSION="$(json_get "$PLUGIN_MANIFEST" version)"
MARKETPLACE_NAME="$(json_get "$MARKETPLACE_MANIFEST" name)"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/ai-scientist" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/ai-scientist" "\$@"
EOF
chmod +x "$BIN_DIR/ai-scientist"

CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
"$VENV_DIR/bin/ai-scientist" agents install --codex-home "$CODEX_HOME_DIR" >/dev/null
agents_message="agents:   installed $CODEX_HOME_DIR/agents"

if ! command -v codex >/dev/null 2>&1; then
  cat >&2 <<EOF
Blocker: codex CLI was not found on PATH.
Evidence: install.sh needs codex plugin add to install $PLUGIN_NAME@$MARKETPLACE_NAME.
Recommended action: Put the Codex CLI on PATH, then rerun ./install.sh. (Recommended)
Alternative action: Install the Python CLI only by running the pip/venv commands manually.
Impact: CLI launcher and agents may be installed, but Codex will keep using the previous plugin cache.
Question: Proceed with option 1 or 2?
EOF
  exit 1
fi

codex plugin add "$PLUGIN_NAME@$MARKETPLACE_NAME"
plugin_message="plugin:  installed $PLUGIN_NAME@$MARKETPLACE_NAME ($PLUGIN_VERSION)"

PLUGIN_CACHE_DIR="${AI_SCIENTIST_PLUGIN_CACHE:-$CODEX_HOME_DIR/plugins/cache/$MARKETPLACE_NAME/$PLUGIN_NAME/$PLUGIN_VERSION}"
if [ ! -d "$PLUGIN_CACHE_DIR" ]; then
  cat >&2 <<EOF
Blocker: Codex did not create the expected plugin cache directory.
Evidence: expected cache path does not exist: $PLUGIN_CACHE_DIR
Recommended action: Check codex plugin list and rerun ./install.sh with AI_SCIENTIST_PLUGIN_CACHE set to the installed cache path. (Recommended)
Alternative action: Bump .codex-plugin/plugin.json version suffix and rerun ./install.sh.
Impact: Codex may keep using a stale cached skill even though the source checkout was updated.
Question: Proceed with option 1 or 2?
EOF
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  cat >&2 <<EOF
Blocker: rsync is required to refresh the Codex plugin cache.
Evidence: cache exists at $PLUGIN_CACHE_DIR, but rsync was not found on PATH.
Recommended action: Install rsync, then rerun ./install.sh. (Recommended)
Alternative action: Rely only on codex plugin add without the post-install cache refresh.
Impact: Codex may keep using stale cached skills/prompts when the manifest version did not change.
Question: Proceed with option 1 or 2?
EOF
  exit 1
fi

mkdir -p "$CACHE_BACKUP_ROOT"
backup_dir="$CACHE_BACKUP_ROOT/$PLUGIN_NAME-$PLUGIN_VERSION.bak-$(date +%Y%m%d%H%M%S)"
cp -a "$PLUGIN_CACHE_DIR" "$backup_dir"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv-ai-scientist/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  "$ROOT/" "$PLUGIN_CACHE_DIR"
cache_message="plugin cache: refreshed $PLUGIN_CACHE_DIR (backup: $backup_dir)"

cat <<EOF
Installed ai-scientist.
  venv:     $VENV_DIR
  launcher: $BIN_DIR/ai-scientist
  python:   $PYTHON_RUNTIME
  $plugin_message
  $agents_message
  $cache_message

Make sure $BIN_DIR is on PATH.
EOF
