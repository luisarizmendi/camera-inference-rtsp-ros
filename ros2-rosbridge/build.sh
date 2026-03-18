#!/usr/bin/env bash
set -e

# --- Defaults ---
REGISTRY="quay.io/luisarizmendi"
CROSS_BUILD=false
PUSH=true

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --cross)
      CROSS_BUILD=true
      shift
      ;;
    --no-push)
      PUSH=false
      shift
      ;;
    --registry)
      REGISTRY="$2"
      shift 2
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
  x86_64) HOST_ARCH="amd64" ;;
  aarch64) HOST_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

cd "$SCRIPT_DIR/src"

echo "========================================"
echo "Image: ${REGISTRY}/${IMAGE_NAME}"
echo "Host arch: ${HOST_ARCH}"
echo "Cross build: ${CROSS_BUILD}"
echo "Push: ${PUSH}"
echo "========================================"
echo ""

# --- Build images ---
BUILT_IMAGES=()

build_image() {
  local arch=$1
  echo "→ Building for $arch..."
  podman build --platform "linux/${arch}" -t "${REGISTRY}/${IMAGE_NAME}:${arch}" .
  BUILT_IMAGES+=("${REGISTRY}/${IMAGE_NAME}:${arch}")
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

# --- Push logic ---
if [[ "$PUSH" == true ]]; then
  echo ""
  echo "→ Recreating manifests (avoiding duplicates)..."

  podman manifest rm "$MANIFEST_PROD" 2>/dev/null || true
  podman manifest create "$MANIFEST_PROD"

  podman manifest rm "$MANIFEST_LATEST" 2>/dev/null || true
  podman manifest create "$MANIFEST_LATEST"

  echo ""
  echo "→ Adding images to manifests..."
  for img in "${BUILT_IMAGES[@]}"; do
    podman manifest add "$MANIFEST_PROD" "$img"
    podman manifest add "$MANIFEST_LATEST" "$img"
  done

  echo ""
  echo "→ Pushing images..."
  for img in "${BUILT_IMAGES[@]}"; do
    podman push "$img"
  done

  echo ""
  echo "→ Pushing manifest: prod"
  podman manifest push "$MANIFEST_PROD"

  echo "→ Pushing manifest: latest"
  podman manifest push "$MANIFEST_LATEST"

  echo ""
  echo "✅ Done."
else
  echo ""
  echo "⚠️ Push disabled. Skipping manifest + push steps."
fi
