# Bundled Rust executable

`bin/omarchy-moza` is the x86-64 Linux build of `rev/`. The moza-rev revision is
pinned in Cargo.toml; Cargo.lock records the dependency graph. Full source and
license notices are included. Python source is tracked separately as described
in [Upstreams.md](Upstreams.md).

## Verification

The **Verify bundled Rust binary** workflow compiles twice in separate clean
target directories, compares the outputs, and compares them with the committed
executable. It verifies the checksum and original Boxflat snapshot, then writes
a report identifying the source commit, package/compiler versions and hashes.

Successful builds of the main branch and release tags receive GitHub artifact
attestations for the binary and report. Pull requests are checked but never
attested. The Release workflow requires both tests and reproduction to pass,
verifies the attestation against the exact release source commit, then publishes
the plugin archive, executable, checksums and report.

```sh
sha256sum --check --strict bin/omarchy-moza.sha256
gh attestation verify bin/omarchy-moza --repo crmne/omarchy-moza \
  --signer-workflow crmne/omarchy-moza/.github/workflows/verify-binary.yml \
  --source-digest "$(git rev-parse HEAD)"
```

An attestation identifies a build's origin; it is not a hardware compatibility
test or a claim that the plugin has been security audited. See
[GitHub's attestation documentation](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).
The original v0.1.0 binary was built locally and has no attestation. This build
and verification process applies from v0.2.0 onward.

## Reproduce locally

The builder image is pinned by digest and installs signed Arch packages from
the 2026-09-02 archive. `tools/build-env.sh` asserts the toolchain versions.
`tools/reproduce-binary.sh` fixes the build epoch, disables incremental builds
and remaps both Cargo and source paths so checkout locations do not affect
the binary. Use Docker on x86-64 Linux:

```sh
docker run --rm -v "$PWD:/source:ro" -w /source \
  archlinux@sha256:84cd9ef000b3cff245ec028e87965b84724f4bf1cc63fc2741ba927b88515ed6 \
  bash -c 'bash tools/build-env.sh && bash tools/reproduce-binary.sh'
```

Run the build-environment script only in that disposable container. To create
a replacement binary after source changes, mount a separate writable output
directory and pass `--output /output/omarchy-moza` to the reproduction script.
Copy the result to `bin/omarchy-moza` and regenerate its `.sha256` file. CI must
verify this new executable before release. `make build` remains available for
local development; a different toolchain may produce different bytes.

The bundled executable requires glibc and libudev on x86-64 Linux. ARM64 remains
a source-build path. Attestations cover only the shipped x86-64 executable.
