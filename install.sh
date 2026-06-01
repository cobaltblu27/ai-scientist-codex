#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Usage: ./install.sh [--python-runtime COMMAND] [--venv-dir PATH] [--bin-dir PATH]

Options:
  --python-runtime COMMAND  Python command used to create the venv. Default: python3
                            Examples: python3.12, /opt/homebrew/bin/python3.12,
                            "conda run -n base python"
  --venv-dir PATH           Venv directory. Default: <repo>/.venv-ai-scientist
  --bin-dir PATH            Directory for ai-scientist launcher. Default: ~/.local/bin
  -h, --help                Show this help.
EOF
}

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_RUNTIME="${AI_SCIENTIST_PYTHON:-python3}"
VENV_DIR="$ROOT/.venv-ai-scientist"
BIN_DIR="$HOME/.local/bin"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --python-runtime)
      [ "$#" -ge 2 ] || { echo "missing value for --python-runtime" >&2; exit 2; }
      PYTHON_RUNTIME="$2"
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

run_python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --upgrade "$ROOT"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/ai-scientist" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/ai-scientist" "\$@"
EOF
chmod +x "$BIN_DIR/ai-scientist"

cat <<EOF
Installed ai-scientist.
  venv:     $VENV_DIR
  launcher: $BIN_DIR/ai-scientist

Make sure $BIN_DIR is on PATH.
EOF
