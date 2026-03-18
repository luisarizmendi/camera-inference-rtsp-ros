#!/usr/bin/env bash
set -e

# --- Defaults ---
REGISTRY=""

# --- Parse args (only extract registry, keep rest) ---
FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --registry)
      REGISTRY="$2"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "========================================"
echo "Running all build.sh scripts"
[[ -n "$REGISTRY" ]] && echo "Registry override: ${REGISTRY}"
echo "Args: ${FORWARD_ARGS[*]}"
echo "========================================"
echo ""

# --- Loop over first-level directories ---
for dir in */ ; do
  dir="${dir%/}"

  if [[ -f "${dir}/build.sh" ]]; then
    echo "========================================"
    echo "→ Running build in: ${dir}"
    echo "========================================"

    (
      cd "$dir"
      chmod +x build.sh
      ./build.sh "${FORWARD_ARGS[@]}"
    )

    echo ""
  fi
done

echo "========================================"
echo "✅ All builds completed"
echo "========================================"
