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
echo "Force manifest reset: ${FORCE_MANIFEST_RESET}"
echo "========================================"
echo ""

# --- Build images ---
BUILT_IMAGES=()

build_image() {
  local arch=$1
  local tag="${REGISTRY}/${IMAGE_NAME}:${arch}"

  echo "→ Building for $arch..."

  # Remove existing tag to avoid conflicts
  podman rmi "$tag" 2>/dev/null || true

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

# --- Functions to handle manifests ---
ensure_manifest() {
  local manifest=$1

  if [[ "$FORCE_MANIFEST_RESET" == true ]]; then
    echo "→ Force reset: $manifest"
    podman manifest rm "$manifest" 2>/dev/null || true
  else
    # Ensure no broken local state
    if ! podman manifest inspect "$manifest" >/dev/null 2>&1; then
      podman manifest rm "$manifest" 2>/dev/null || true
    fi
  fi

  echo "→ Creating manifest: $manifest"
  podman manifest create "$manifest"
}

add_images_to_manifest() {
  local manifest=$1

  for img in "${BUILT_IMAGES[@]}"; do
    echo "→ Adding $img to $manifest"

    arch=$(echo "$img" | awk -F: '{print $2}')

    # Remove same-arch entry if exists (ignore errors)
    podman manifest remove "$manifest" \
      "docker://${REGISTRY}/${IMAGE_NAME}:${arch}" \
      2>/dev/null || true

    podman manifest add "$manifest" "$img"
  done
}

# --- Push logic ---
if [[ "$PUSH" == true ]]; then
  echo ""
  echo "→ Preparing manifests..."

  ensure_manifest "$MANIFEST_PROD"
  ensure_manifest "$MANIFEST_LATEST"

  echo ""
  echo "→ Updating manifests..."
  add_images_to_manifest "$MANIFEST_PROD"
  add_images_to_manifest "$MANIFEST_LATEST"

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
