PYTHON ?= python3
PREFIX ?= $(HOME)/.local
BIN_DIR := $(PREFIX)/bin
RUNTIME_ROOT := $(CURDIR)/runtime
INSTALL_MODE ?= codex

.PHONY: test install-local

test:
	$(PYTHON) -m pytest -q

install-local:
	mkdir -p "$(BIN_DIR)"
ifeq ($(INSTALL_MODE),codex)
	cp "$(CURDIR)/scripts/launch-installed-persona.py" "$(BIN_DIR)/opl-persona"
else ifeq ($(INSTALL_MODE),standalone)
	mkdir -p "$(PREFIX)/share/opl-persona"
	cp -R "$(CURDIR)/opl-package.json" "$(CURDIR)/bin" "$(CURDIR)/runtime" "$(CURDIR)/skills" "$(CURDIR)/assets" "$(PREFIX)/share/opl-persona/"
	printf '%s\n' '#!/usr/bin/env bash' 'PACKAGE_ROOT="$$(cd "$$(dirname "$$0")/../share/opl-persona" && pwd)"' 'PYTHONPATH="$$PACKAGE_ROOT/runtime$${PYTHONPATH:+:$$PYTHONPATH}" exec "$(PYTHON)" -m opl_persona "$$@"' > "$(BIN_DIR)/opl-persona"
else
	$(error INSTALL_MODE must be codex or standalone)
endif
	chmod +x "$(BIN_DIR)/opl-persona"
