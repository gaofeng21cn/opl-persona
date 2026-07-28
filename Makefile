PYTHON ?= python3
PREFIX ?= $(HOME)/.local
BIN_DIR := $(PREFIX)/bin
RUNTIME_ROOT := $(CURDIR)/plugins/opl-persona/runtime

.PHONY: test install-local

test:
	$(PYTHON) -m pytest -q

install-local:
	mkdir -p "$(BIN_DIR)"
	printf '%s\n' '#!/usr/bin/env bash' 'PYTHONPATH="$(RUNTIME_ROOT)" exec "$(PYTHON)" -m opl_persona "$$@"' > "$(BIN_DIR)/opl-persona"
	chmod +x "$(BIN_DIR)/opl-persona"
