#!/usr/bin/env bash
# --output copies the matching rebuilds; default also verifies the shipped binaries.
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
# The Proton helper for ACC and LMU: a static PE without a link timestamp.
for build in a b; do
  x86_64-w64-mingw32-gcc -std=c11 -O2 -Wall -Wextra -Werror -s -static -mwindows \
    -ffile-prefix-map="$PWD=/source" -Wl,--no-insert-timestamp \
    -o "$build_root/$build/omarchy-moza-shm.exe" shm-bridge/omarchy-moza-shm.c -lws2_32
done
cmp "$build_root/a/omarchy-moza-shm.exe" "$build_root/b/omarchy-moza-shm.exe"
if [[ "${1:-}" == --output && $# == 2 ]]; then
  install -Dm755 "$build_root/a/release/omarchy-moza" "$2"
  install -Dm755 "$build_root/a/omarchy-moza-shm.exe" "$(dirname "$2")/omarchy-moza-shm.exe"
else
  test $# == 0
  cmp "$build_root/a/release/omarchy-moza" bin/omarchy-moza
  cmp "$build_root/a/omarchy-moza-shm.exe" bin/omarchy-moza-shm.exe
  sha256sum --check --strict bin/omarchy-moza.sha256 bin/omarchy-moza-shm.exe.sha256
fi
