PYTHON ?= python3
PREFIX ?= $(HOME)/.local
BIN_DIR := $(PREFIX)/bin
RUNTIME_ROOT := $(CURDIR)/plugins/opl-persona/runtime

.PHONY: test check-framework-support install-local

test:
	@if [ -n "$(OPL_FRAMEWORK_ROOT)" ]; then $(MAKE) check-framework-support; fi
	$(PYTHON) -m pytest -q

check-framework-support:
	@test -n "$(OPL_FRAMEWORK_ROOT)" || { echo 'Set OPL_FRAMEWORK_ROOT to the Framework checkout'; exit 1; }
	node "$(OPL_FRAMEWORK_ROOT)/scripts/materialize-python-support.mjs" --module profile_workspace --target plugins/opl-persona/runtime/opl_persona/_opl_profile_workspace.py --check

install-local:
	mkdir -p "$(BIN_DIR)"
	printf '%s\n' '#!/usr/bin/env bash' 'PYTHONPATH="$(RUNTIME_ROOT)" exec "$(PYTHON)" -m opl_persona "$$@"' > "$(BIN_DIR)/opl-persona"
	chmod +x "$(BIN_DIR)/opl-persona"
