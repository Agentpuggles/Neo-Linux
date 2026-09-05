# Development shortcuts for neo. Everything here is optional — the launcher itself
# needs no build step. CI runs `make check`.

PYTHON ?= python3
RUFF   ?= ruff
PREFIX ?= $(HOME)/.local

# The CLI is stdlib-only and deliberately runs on the system interpreter, so
# $(PYTHON) stays as-is. The desktop app needs PySide6, which `make dev-gui`
# installs into .venv — so the GUI targets prefer that interpreter when it
# exists and fall back to $(PYTHON) otherwise (a distro-packaged PySide6, or
# an already-activated virtualenv). Override with `make run-gui GUI_PYTHON=...`.
VENV_PYTHON := $(CURDIR)/.venv/bin/python
GUI_PYTHON  ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(PYTHON))

.DEFAULT_GOAL := help

.PHONY: help check check-gui lint lint-fix format test test-gui smoke smoke-gui \
	dev dev-gui gui-python-check install install-gui install-all uninstall \
	uninstall-all clean run-gui

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check: lint test smoke  ## Everything CI runs (CLI only — no Qt needed)

check-gui: check test-gui smoke-gui  ## Everything CI runs, including the desktop app

lint:  ## Ruff over the launcher, the GUI and the tests
	$(RUFF) check . neo gui/neo-gui

lint-fix:  ## Ruff, applying safe fixes
	$(RUFF) check --fix . neo gui/neo-gui

format:  ## Format the tests only (`neo` is hand-formatted; see ruff.toml)
	$(RUFF) format tests

# The Qt tests live in test_gui_widgets and are an order of magnitude slower,
# so `make test` covers everything else and `make test-gui` covers those.
test:  ## Offline unit tests for the CLI and the GUI backend (no Qt required)
	$(PYTHON) -m unittest discover -s tests -t . -v -p 'test_[a-fh-z]*.py'
	$(PYTHON) -m unittest tests.test_gui_backend -v

test-gui: gui-python-check  ## Qt tests, driven offscreen (needs PySide6; ~8 min)
	QT_QPA_PLATFORM=offscreen $(GUI_PYTHON) -m unittest tests.test_gui_widgets -v

smoke:  ## Byte-compile and run the CLI the way a user would
	$(PYTHON) -m py_compile neo
	$(PYTHON) neo --version
	@for cmd in login whoami setup logout status list config install verify launch; do \
		$(PYTHON) neo $$cmd --help > /dev/null || exit 1; \
	done
	@echo "smoke: ok"

smoke-gui: gui-python-check  ## Import the desktop app and open every page once, headless
	$(GUI_PYTHON) -m py_compile gui/neo-gui
	QT_QPA_PLATFORM=offscreen $(GUI_PYTHON) gui/neo-gui --self-check

dev:  ## Install the one dev dependency (ruff) into a venv
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade ruff
	@echo "run:  source .venv/bin/activate"

dev-gui: dev  ## Same, plus PySide6 so you can run the desktop app
	.venv/bin/pip install --upgrade PySide6
	@echo "the GUI targets (run-gui, test-gui, smoke-gui) now use .venv automatically"

run-gui: gui-python-check  ## Run the desktop app from the checkout
	NEO_BIN=$(CURDIR)/neo $(GUI_PYTHON) gui/neo-gui

# Fail with an instruction rather than a ModuleNotFoundError traceback.
gui-python-check:
	@$(GUI_PYTHON) -c 'import PySide6' 2>/dev/null || { \
		echo "PySide6 not found for $(GUI_PYTHON)."; \
		echo "Run 'make dev-gui' to create .venv with PySide6, or install your"; \
		echo "distro's package (e.g. pacman -S pyside6), or set GUI_PYTHON=..."; \
		exit 1; }

install:  ## Install the CLI into $(PREFIX)/bin
	install -Dm755 neo $(DESTDIR)$(PREFIX)/bin/neo

install-gui: install  ## Install the desktop app, its .desktop entry and icon
	install -d $(DESTDIR)$(PREFIX)/share/neo
	# --exclude keeps __pycache__ out of the package: those .pyc files are
	# stamped with the build machine's paths and Python version.
	tar -c --exclude=__pycache__ --exclude='*.pyc' -C gui neogui \
		| tar -x -C $(DESTDIR)$(PREFIX)/share/neo
	install -Dm755 gui/neo-gui $(DESTDIR)$(PREFIX)/bin/neo-gui
	install -Dm644 packaging/dev.neofn.NeoLauncher.desktop \
		$(DESTDIR)$(PREFIX)/share/applications/dev.neofn.NeoLauncher.desktop
	install -Dm644 packaging/dev.neofn.NeoLauncher.svg \
		$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/dev.neofn.NeoLauncher.svg
	install -Dm644 packaging/dev.neofn.NeoLauncher.metainfo.xml \
		$(DESTDIR)$(PREFIX)/share/metainfo/dev.neofn.NeoLauncher.metainfo.xml

install-all: install-gui  ## CLI + desktop app (what distro packages call)

uninstall:  ## Remove the CLI
	rm -f $(DESTDIR)$(PREFIX)/bin/neo

uninstall-all: uninstall  ## Remove everything, including the desktop entry
	rm -f $(DESTDIR)$(PREFIX)/bin/neo-gui
	rm -rf $(DESTDIR)$(PREFIX)/share/neo
	rm -f $(DESTDIR)$(PREFIX)/share/applications/dev.neofn.NeoLauncher.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/dev.neofn.NeoLauncher.svg
	rm -f $(DESTDIR)$(PREFIX)/share/metainfo/dev.neofn.NeoLauncher.metainfo.xml

clean:  ## Delete caches and build droppings
	rm -rf __pycache__ .pytest_cache .ruff_cache build
	find gui -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
