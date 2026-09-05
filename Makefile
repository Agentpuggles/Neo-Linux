# Development shortcuts for neo. Everything here is optional — the launcher itself
# needs no build step. CI runs `make check`.

PYTHON ?= python3
RUFF   ?= ruff
PREFIX ?= $(HOME)/.local

.DEFAULT_GOAL := help

.PHONY: help check lint lint-fix format test test-gui smoke smoke-gui dev dev-gui \
	install install-gui install-all uninstall uninstall-all clean run-gui

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

test-gui:  ## Qt tests, driven offscreen (needs PySide6; no display server; ~8 min)
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m unittest tests.test_gui_widgets -v

smoke:  ## Byte-compile and run the CLI the way a user would
	$(PYTHON) -m py_compile neo
	$(PYTHON) neo --version
	@for cmd in login whoami setup logout status list config install verify launch; do \
		$(PYTHON) neo $$cmd --help > /dev/null || exit 1; \
	done
	@echo "smoke: ok"

smoke-gui:  ## Import the desktop app and open every page once, headless
	$(PYTHON) -m py_compile gui/neo-gui
	QT_QPA_PLATFORM=offscreen $(PYTHON) gui/neo-gui --self-check

dev:  ## Install the one dev dependency (ruff) into a venv
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade ruff
	@echo "run:  source .venv/bin/activate"

dev-gui: dev  ## Same, plus PySide6 so you can run the desktop app
	.venv/bin/pip install --upgrade PySide6

run-gui:  ## Run the desktop app from the checkout
	NEO_BIN=$(CURDIR)/neo $(PYTHON) gui/neo-gui

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
