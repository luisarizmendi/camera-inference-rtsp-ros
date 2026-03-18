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

# --- Pull remote images for arches we did NOT build, so they land in local storage
#     and can be reliably included in the new manifest.
#     Returns nothing; populates PRESERVED_IMAGES array.
PRESERVED_IMAGES=()

pull_missing_arches() {
  if [[ "$FORCE_MANIFEST_RESET" == true ]]; then
    echo "  (force-manifest-reset: skipping preservation of existing remote arches)"
    return
  fi

  # Use the :prod manifest as the source of truth for what already exists remotely.
  # (Both prod and latest should be in sync, so one inspect is enough.)
  echo "→ Inspecting remote manifest for arches to preserve: ${MANIFEST_PROD}"
  local inspect_json
  if ! inspect_json=$(podman manifest inspect "docker://${MANIFEST_PROD}" 2>/dev/null); then
    echo "  (no existing remote manifest found — starting fresh)"
    return
  fi

  local remote_arches
  remote_arches=$(echo "$inspect_json" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('manifests', []):
    arch = m.get('platform', {}).get('architecture')
    if arch:
        print(arch)
" 2>/dev/null || true)

  for remote_arch in $remote_arches; do
    # Skip arches we just rebuilt — we'll use the freshly built local image
    local rebuilt=false
    for built_arch in "${BUILT_ARCHES[@]}"; do
      if [[ "$built_arch" == "$remote_arch" ]]; then
        rebuilt=true
        break
      fi
    done

    if [[ "$rebuilt" == true ]]; then
      echo "  → Arch '${remote_arch}' was rebuilt this run — skipping pull"
      continue
    fi

    local arch_tag="${REGISTRY}/${IMAGE_NAME}:${remote_arch}"
    echo "  → Pulling remote arch '${remote_arch}' to preserve it: ${arch_tag}"
    if podman pull --platform "linux/${remote_arch}" "${arch_tag}"; then
      PRESERVED_IMAGES+=("$arch_tag")
    else
      echo "  ⚠️  Could not pull ${arch_tag} — skipping (will not appear in new manifest)"
    fi
  done
}

# --- Build a fresh local manifest from: preserved pulled images + newly built images ---
build_manifest() {
  local manifest=$1

  # Remove any stale local copy
  podman manifest rm "$manifest" 2>/dev/null || true
  podman rmi --force "$manifest" 2>/dev/null || true

  echo "→ Creating manifest: $manifest"
  podman manifest create "$manifest"

  # Add preserved (pulled) images first
  for img in "${PRESERVED_IMAGES[@]}"; do
    echo "  → Adding preserved arch image: $img"
    podman manifest add "$manifest" "$img"
  done

  # Add freshly built images
  for img in "${BUILT_IMAGES[@]}"; do
    echo "  → Adding newly built image: $img"
    podman manifest add "$manifest" "$img"
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
  echo "→ Pulling remote arches we didn't build (to preserve them in the manifest)..."
  pull_missing_arches

  echo ""
  echo "→ Building merged manifests..."
  build_manifest "$MANIFEST_PROD"
  build_manifest "$MANIFEST_LATEST"

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