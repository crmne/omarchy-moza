PLUGIN_DIR ?= $(HOME)/.config/omarchy/plugins/crmne.moza
ARCH := $(shell uname -m)
BINARY := bin/omarchy-moza$(if $(filter x86_64,$(ARCH)),,-$(ARCH))

.PHONY: build test install validate verify-binary verify-upstream
build:
	cargo build --release --locked --manifest-path rev/Cargo.toml
	install -Dm755 rev/target/release/omarchy-moza $(BINARY)
	sha256sum $(BINARY) > $(BINARY).sha256

test:
	python3 -B tools/boxflat-source.py
	cargo test --locked --manifest-path rev/Cargo.toml
	cargo clippy --locked --manifest-path rev/Cargo.toml --all-targets -- -D warnings
	/usr/bin/python3 -B -m unittest discover -s tests -v

validate:
	@stage=$$(mktemp -d); trap 'rm -rf "$$stage"' EXIT; \
	rsync -a --exclude=.git --exclude=target --exclude=__pycache__ --exclude=.cache ./ "$$stage/"; \
	omarchy plugin validate "$$stage"

verify-upstream:
	python3 -B tools/boxflat-source.py --upstream

verify-binary:
	bash tools/reproduce-binary.sh

install: validate
	mkdir -p "$(PLUGIN_DIR)"
	rsync -a --exclude=.git --exclude=target --exclude=__pycache__ --exclude=.cache ./ "$(PLUGIN_DIR)/"
	omarchy-shell shell rescanPlugins
	@echo 'Enable with: omarchy plugin enable crmne.moza'
