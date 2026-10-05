#!/usr/bin/env bash
# Run only inside the pinned disposable build container, never on a user's host.
set -euo pipefail
test -f /.dockerenv
# These are pacman's mirror placeholders, expanded by pacman itself.
# shellcheck disable=SC2016
printf '%s\n' 'Server = https://archive.archlinux.org/repos/2026/09/02/$repo/os/$arch' > /etc/pacman.d/mirrorlist
pacman -Syy --noconfirm
pacman -S --noconfirm --needed rust gcc binutils git python pkgconf systemd-libs
test "$(pacman -Q rust)" = 'rust 1:1.98.0-1'
test "$(pacman -Q gcc)" = 'gcc 16.2.1+r23+gd564253eb6c8-1'
test "$(pacman -Q gcc-libs)" = 'gcc-libs 16.2.1+r23+gd564253eb6c8-1'
test "$(pacman -Q binutils)" = 'binutils 2.47-4'
test "$(pacman -Q glibc)" = 'glibc 2.44+r24+g16be1518495f-1'
test "$(pacman -Q git)" = 'git 2.55.0-1'
test "$(pacman -Q python)" = 'python 3.14.7-1'
test "$(pacman -Q pkgconf)" = 'pkgconf 3.0.6-1'
test "$(pacman -Q systemd-libs)" = 'systemd-libs 261.2-1'
