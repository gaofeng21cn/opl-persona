PYTHON ?= python3
PREFIX ?= $(HOME)/.local
BIN_DIR := $(PREFIX)/bin
RUNTIME_ROOT := $(CURDIR)/plugins/opl-persona/runtime
INSTALL_MODE ?= codex

.PHONY: test check-framework-support install-local

test:
	@if [ -n "$(OPL_FRAMEWORK_ROOT)" ]; then $(MAKE) check-framework-support; fi
	$(PYTHON) -m pytest -q

check-framework-support:
	@test -n "$(OPL_FRAMEWORK_ROOT)" || { echo 'Set OPL_FRAMEWORK_ROOT to the Framework checkout'; exit 1; }
	node "$(OPL_FRAMEWORK_ROOT)/scripts/materialize-python-support.mjs" --module profile_workspace --target plugins/opl-persona/runtime/opl_persona/_opl_profile_workspace.py --check

install-local:
	mkdir -p "$(BIN_DIR)"
ifeq ($(INSTALL_MODE),codex)
	cp "$(CURDIR)/scripts/launch-installed-persona.py" "$(BIN_DIR)/opl-persona"
else ifeq ($(INSTALL_MODE),standalone)
	mkdir -p "$(PREFIX)/share/opl-persona"
	cp -R "$(CURDIR)/plugins/opl-persona/." "$(PREFIX)/share/opl-persona/"
	printf '%s\n' '#!/usr/bin/env bash' 'PACKAGE_ROOT="$$(cd "$$(dirname "$$0")/../share/opl-persona" && pwd)"' 'PYTHONPATH="$$PACKAGE_ROOT/runtime$${PYTHONPATH:+:$$PYTHONPATH}" exec "$(PYTHON)" -m opl_persona "$$@"' > "$(BIN_DIR)/opl-persona"
else
	$(error INSTALL_MODE must be codex or standalone)
endif
	chmod +x "$(BIN_DIR)/opl-persona"
