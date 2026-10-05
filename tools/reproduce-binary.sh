#!/usr/bin/env bash
# --output copies the two matching rebuilds; default also verifies the shipped ELF.
set -euo pipefail
cd "$(dirname "$0")/.."
export CARGO_HOME="${CARGO_HOME:-/tmp/moza-cargo-home}"
export CARGO_INCREMENTAL=0 SOURCE_DATE_EPOCH=1788307200
export RUSTFLAGS="--remap-path-prefix=$CARGO_HOME=/cargo-home --remap-path-prefix=$PWD=/source"
build_root=$(mktemp -d)
trap 'rm -rf "$build_root"' EXIT
for build in a b; do
  cargo build --release --locked --manifest-path rev/Cargo.toml --target-dir "$build_root/$build"
done
cmp "$build_root/a/release/omarchy-moza" "$build_root/b/release/omarchy-moza"
if [[ "${1:-}" == --output && $# == 2 ]]; then
  install -Dm755 "$build_root/a/release/omarchy-moza" "$2"
else
  test $# == 0
  cmp "$build_root/a/release/omarchy-moza" bin/omarchy-moza
  sha256sum --check --strict bin/omarchy-moza.sha256
fi
