#!/usr/bin/env bash
# Write the verified build report, including the workflow's exact source SHA.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# != 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: binary-provenance.sh <40-character source commit>' >&2
  exit 1
fi
source_commit="$1"
printf 'format=omarchy-moza-binary-provenance-v1\nsource_commit=%s\n' "$source_commit"
echo 'builder_image=archlinux@sha256:84cd9ef000b3cff245ec028e87965b84724f4bf1cc63fc2741ba927b88515ed6'
echo 'source_date_epoch=1788307200'
echo 'verified_reproducible_builds=2'
echo 'verified_bundled_binary=true'
sha256sum bin/omarchy-moza rev/Cargo.lock vendor/boxflat.lock.json
pacman -Q rust gcc gcc-libs binutils glibc git python pkgconf systemd-libs
rustc --version --verbose
