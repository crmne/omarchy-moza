# Bundled Rust executable

bin/omarchy-moza is the x86-64 Linux build of rev/. The moza-rev revision is
pinned in Cargo.toml; dependency resolution is recorded in Cargo.lock. Source
and license notices are included.

```sh
sha256sum -c bin/omarchy-moza.sha256
make build
```

The initial binary was built on Arch Linux and needs glibc and libudev.
Build locally on incompatible systems. ARM64 is a source-build path until a
checked binary is bundled. This initial artifact has not undergone independent
reproducible-build verification or signing. CI tests the source independently.
