JIRA_ENDPOINT ?=
RULESDIR      ?= $(HOME)/.cursor/rules
BUILDDIR      := build

RULE_TEMPLATES := $(wildcard cursor/*.mdc.in)
RULES_GEN      := $(patsubst cursor/%.mdc.in,$(BUILDDIR)/cursor/%.mdc,$(RULE_TEMPLATES))

.PHONY: all cursor install install-cursor install-python check-vars clean test test-python lint fmt docs man

all: check-vars cursor ## Build generated files (default)

check-vars:
	@test -n "$(JIRA_ENDPOINT)" || \
	  (printf 'error: JIRA_ENDPOINT is required\nUsage: make JIRA_ENDPOINT=yourorg.atlassian.net [install]\n' >&2 && false)

cursor: check-vars $(RULES_GEN) ## Build cursor rules from .mdc.in

$(BUILDDIR)/cursor/%.mdc: cursor/%.mdc.in | $(BUILDDIR)/cursor
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' $< > $@

$(BUILDDIR)/cursor:
	mkdir -p $@

install: all install-cursor install-python ## Build + install rules + sync Python venv

install-cursor: cursor
	install -d $(RULESDIR) .cursor/rules
	install -m 644 $(BUILDDIR)/cursor/* -t $(RULESDIR)
	install -m 644 $(BUILDDIR)/cursor/* -t .cursor/rules

install-python: ## Sync Python venv via uv
	uv sync --all-extras

test: test-python ## Run all tests

test-python: ## Run Python tests
	uv run pytest tests/ -v

lint: ## Run ruff linter and formatter check
	uv run ruff check notegraph/ tests/
	uv run ruff format --check notegraph/ tests/

fmt: ## Auto-format with ruff
	uv run ruff check --fix notegraph/ tests/
	uv run ruff format notegraph/ tests/

docs: ## Build HTML documentation
	uv run sphinx-build -b html docs/ $(BUILDDIR)/docs/html

man: ## Build man page
	uv run sphinx-build -b man docs/ $(BUILDDIR)/docs/man

clean: ## Remove build directory and workspace rules
	rm -rf $(BUILDDIR) .cursor/rules/*.mdc
