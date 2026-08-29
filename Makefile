# Development shortcuts for neo. Everything here is optional — the launcher itself
# needs no build step. CI runs `make check`.

PYTHON ?= python3
RUFF   ?= ruff
PREFIX ?= $(HOME)/.local

.DEFAULT_GOAL := help

.PHONY: help check lint lint-fix format test smoke dev install uninstall clean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check: lint test smoke  ## Everything CI runs

lint:  ## Ruff over the launcher and the tests
	$(RUFF) check . neo

lint-fix:  ## Ruff, applying safe fixes
	$(RUFF) check --fix . neo

format:  ## Format the tests only (`neo` is hand-formatted; see ruff.toml)
	$(RUFF) format tests

test:  ## Offline unit tests (no network, no writes to your real ~/.local/share)
	$(PYTHON) -m unittest discover -s tests -t . -v

smoke:  ## Byte-compile and run the CLI the way a user would
	$(PYTHON) -m py_compile neo
	$(PYTHON) neo --version
	@for cmd in login whoami setup logout status list config install verify launch; do \
		$(PYTHON) neo $$cmd --help > /dev/null || exit 1; \
	done
	@echo "smoke: ok"

dev:  ## Install the one dev dependency (ruff) into a venv
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade ruff
	@echo "run:  source .venv/bin/activate"

install:  ## Install the launcher into $(PREFIX)/bin
	install -Dm755 neo $(PREFIX)/bin/neo
	@$(PREFIX)/bin/neo --version

uninstall:  ## Remove it again
	rm -f $(PREFIX)/bin/neo

clean:  ## Delete caches and build droppings
	rm -rf __pycache__ .pytest_cache .ruff_cache
	find . -name '*.pyc' -delete
