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

# --- Architectures built this run (e.g. "amd64", "arm64") ---
BUILT_ARCHES=()
for img in "${BUILT_IMAGES[@]}"; do
  BUILT_ARCHES+=("$(basename "$img" | sed 's/.*://')")
done

# --- Clean local manifest and recreate it, preserving remote arches we didn't build ---
#
# Logic:
#   1. If FORCE_MANIFEST_RESET=true  → start from scratch (original behaviour).
#   2. Otherwise, inspect the existing remote manifest and re-add any arch-specific
#      tags that were NOT rebuilt this run, so they are carried forward.
#
prepare_manifest() {
  local manifest=$1

  # Remove any stale local copy
  podman manifest rm  "$manifest" 2>/dev/null || true
  podman rmi --force  "$manifest" 2>/dev/null || true

  echo "→ Creating manifest: $manifest"
  podman manifest create "$manifest"

  if [[ "$FORCE_MANIFEST_RESET" == true ]]; then
    echo "  (force-manifest-reset: skipping preservation of existing remote arches)"
    return
  fi

  # Pull the existing remote manifest and harvest arches we didn't rebuild
  echo "→ Checking remote manifest for arches to preserve: $manifest"
  local inspect_json
  if inspect_json=$(podman manifest inspect "docker://${manifest}" 2>/dev/null); then
    # Extract every architecture listed in the remote manifest
    local remote_arches
    remote_arches=$(echo "$inspect_json" \
      | python3 -c "
import sys, json
data = json.load(sys.stdin)
arches = set()
for m in data.get('manifests', []):
    arch = m.get('platform', {}).get('architecture')
    if arch:
        arches.add(arch)
for a in sorted(arches):
    print(a)
" 2>/dev/null || true)

    for remote_arch in $remote_arches; do
      # Skip arches we just rebuilt — those will be added fresh below
      local rebuilt=false
      for built_arch in "${BUILT_ARCHES[@]}"; do
        if [[ "$built_arch" == "$remote_arch" ]]; then
          rebuilt=true
          break
        fi
      done

      if [[ "$rebuilt" == false ]]; then
        local arch_tag="${REGISTRY}/${IMAGE_NAME}:${remote_arch}"
        echo "  → Preserving existing remote arch '${remote_arch}' from ${arch_tag}"
        podman manifest add "$manifest" "docker://${arch_tag}" || \
          echo "  ⚠️  Could not add ${arch_tag} — skipping (image may not exist as a standalone tag)"
      else
        echo "  → Arch '${remote_arch}' was rebuilt this run — will be replaced"
      fi
    done
  else
    echo "  (no existing remote manifest found — starting fresh)"
  fi
}

# --- Add newly built images to the manifest via their registry digests ---
add_built_images_to_manifest() {
  local manifest=$1
  for img in "${BUILT_IMAGES[@]}"; do
    echo "→ Adding $img to $manifest"
    podman manifest add "$manifest" "docker://${img}"
  done
}

# --- Push logic ---
if [[ "$PUSH" == true ]]; then
  echo ""
  echo "→ Pushing arch-specific images first..."
  for img in "${BUILT_IMAGES[@]}"; do
    podman push "$img"
  done

  echo ""
  echo "→ Preparing manifests (merging with existing remote)..."
  prepare_manifest "$MANIFEST_PROD"
  prepare_manifest "$MANIFEST_LATEST"

  echo ""
  echo "→ Adding newly built images to manifests..."
  add_built_images_to_manifest "$MANIFEST_PROD"
  add_built_images_to_manifest "$MANIFEST_LATEST"

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