#!/usr/bin/env bash
# --output copies the two matching rebuilds; default also verifies the shipped ELF.
set -euo pipefail
cd "$(dirname "$0")/.."
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-moza"
mkdir -p "$cache_root"
export CARGO_HOME="${CARGO_HOME:-$cache_root/cargo}"
export CARGO_INCREMENTAL=0 SOURCE_DATE_EPOCH=1788307200
export RUSTFLAGS="--remap-path-prefix=$CARGO_HOME=/cargo-home --remap-path-prefix=$PWD=/source"
build_root=$(mktemp -d "$cache_root/reproduce.XXXXXXXX")
trap 'rm -rf "$build_root"' EXIT
for build in a b; do
  # Each independent build starts with an empty store, without remote restores.
  env -u MBX_REMOTE_URL -u MBX_REMOTE_MODE XDG_CONFIG_HOME="$build_root/config" \
    MBX_CACHE_DIR="$build_root/$build-cache" MBX_TARGET_ROOT="$build_root/$build-targets" \
    mbx build --release --locked --manifest-path rev/Cargo.toml --target-dir "$build_root/$build"
done
cmp "$build_root/a/release/omarchy-moza" "$build_root/b/release/omarchy-moza"
if [[ "${1:-}" == --output && $# == 2 ]]; then
  install -Dm755 "$build_root/a/release/omarchy-moza" "$2"
else
  test $# == 0
  cmp "$build_root/a/release/omarchy-moza" bin/omarchy-moza
  sha256sum --check --strict bin/omarchy-moza.sha256
fi
