#!/usr/bin/env bash
set -e

# --- Defaults ---
REGISTRY="quay.io/luisarizmendi"
CROSS_BUILD=false
PUSH=true
FORCE_MANIFEST_RESET=false

# --- Parse args ---
FORWARD_ARGS=()
while [[ $# -gt 0 ]]; do
  case $1 in
    --cross)
      CROSS_BUILD=true
      FORWARD_ARGS+=("$1")
      shift
      ;;
    --no-push)
      PUSH=false
      FORWARD_ARGS+=("$1")
      shift
      ;;
    --registry)
      REGISTRY="$2"
      FORWARD_ARGS+=("$1" "$2")
      shift 2
      ;;
    --force-manifest-reset)
      FORCE_MANIFEST_RESET=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# --- Get script directory name as IMAGE_NAME ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="$(basename "$SCRIPT_DIR")"

# --- Detect host architecture ---
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  HOST_ARCH="amd64" ;;
  aarch64) HOST_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

cd "$SCRIPT_DIR/src"

echo "========================================"
echo "Image: ${REGISTRY}/${IMAGE_NAME}"
echo "Host arch: ${HOST_ARCH}"
echo "Cross build: ${CROSS_BUILD}"
echo "Push: ${PUSH}"
echo "Force manifest reset: ${FORCE_MANIFEST_RESET}"
echo "========================================"
echo ""

# --- Build images ---
BUILT_IMAGES=()

build_image() {
  local arch=$1
  local tag="${REGISTRY}/${IMAGE_NAME}:${arch}"
  echo "→ Building for $arch..."
  podman build --platform "linux/${arch}" -t "$tag" .
  BUILT_IMAGES+=("$tag")
}

# Always build native
build_image "$HOST_ARCH"

# Cross-build if enabled
if [[ "$CROSS_BUILD" == true ]]; then
  if [[ "$HOST_ARCH" == "amd64" ]]; then
    build_image "arm64"
  elif [[ "$HOST_ARCH" == "arm64" ]]; then
    build_image "amd64"
  fi
fi

# --- Manifest names ---
MANIFEST_PROD="${REGISTRY}/${IMAGE_NAME}:prod"
MANIFEST_LATEST="${REGISTRY}/${IMAGE_NAME}:latest"

# --- Architectures built this run ---
BUILT_ARCHES=()
for img in "${BUILT_IMAGES[@]}"; do
  BUILT_ARCHES+=("$(basename "$img" | sed 's/.*://')")
done

# ---------------------------------------------------------------------------
# merge_manifest <manifest_tag>
#
# Strategy: seed the local manifest by cloning the remote one, then swap out
# only the entries for arches we rebuilt.  All other arch entries are carried
# forward untouched because they were part of the cloned manifest from the start.
#
# `podman manifest create <name> docker://<remote>` does the clone — it pulls
# the manifest list metadata (not the image layers) and stores it locally,
# giving us a starting point that already contains every existing arch entry.
# ---------------------------------------------------------------------------
merge_manifest() {
  local manifest=$1

  # Clean up any stale local copy
  podman manifest rm  "$manifest" 2>/dev/null || true
  podman rmi --force  "$manifest" 2>/dev/null || true

  if [[ "$FORCE_MANIFEST_RESET" == false ]] && \
     podman manifest inspect "docker://${manifest}" &>/dev/null; then

    echo "→ Seeding local manifest from remote: ${manifest}"
    podman manifest create "$manifest" "docker://${manifest}"

    # Remove the stale entry for each arch we are about to replace
    for arch in "${BUILT_ARCHES[@]}"; do
      local digest
      digest=$(podman manifest inspect "$manifest" 2>/dev/null \
        | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('manifests', []):
    if m.get('platform', {}).get('architecture') == '${arch}':
        print(m['digest'])
        break
" 2>/dev/null || true)

      if [[ -n "$digest" ]]; then
        echo "  → Removing stale ${arch} entry (${digest:0:19}...) to replace with fresh build"
        podman manifest remove "$manifest" "$digest"
      fi
    done

  else
    if [[ "$FORCE_MANIFEST_RESET" == true ]]; then
      echo "→ Creating fresh manifest (--force-manifest-reset): ${manifest}"
    else
      echo "→ No existing remote manifest — creating fresh: ${manifest}"
    fi
    podman manifest create "$manifest"
  fi

  # Add freshly built images
  for img in "${BUILT_IMAGES[@]}"; do
    local arch
    arch=$(basename "$img" | sed 's/.*://')
    echo "  → Adding rebuilt ${arch}: ${img}"
    podman manifest add "$manifest" "$img"
  done

  echo "  Manifest contents after merge:"
  podman manifest inspect "$manifest" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('manifests', []):
    arch   = m.get('platform', {}).get('architecture', '?')
    digest = m.get('digest', '')
    print(f'    {arch}  →  {digest[:19]}...')
"
}

# --- Push logic ---
if [[ "$PUSH" == true ]]; then
  echo ""
  echo "→ Pushing arch-specific images..."
  for img in "${BUILT_IMAGES[@]}"; do
    podman push "$img"
  done

  echo ""
  echo "→ Merging manifests..."
  merge_manifest "$MANIFEST_PROD"
  merge_manifest "$MANIFEST_LATEST"

  echo ""
  echo "→ Pushing manifest: prod"
  podman manifest push --rm "$MANIFEST_PROD"
  echo "→ Pushing manifest: latest"
  podman manifest push --rm "$MANIFEST_LATEST"

  echo ""
  echo "✅ Done."
else
  echo ""
  echo "⚠️  Push disabled. Skipping manifest + push steps."
fi