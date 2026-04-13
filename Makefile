JIRA_ENDPOINT ?=
BINDIR        ?= $(HOME)/.local/bin
RULESDIR      ?= $(HOME)/.cursor/rules
SCRIPT_DIR    ?= $(BINDIR)
BUILDDIR      := build

SCRIPT_TEMPLATES := scripts/gh-note.sh.in scripts/jira-note.sh.in scripts/todo-page.sh.in
RULE_TEMPLATES   := $(wildcard cursor/*.mdc.in)

SCRIPTS_GEN := $(patsubst scripts/%.sh.in,$(BUILDDIR)/scripts/%.sh,$(SCRIPT_TEMPLATES))
RULES_GEN   := $(patsubst cursor/%.mdc.in,$(BUILDDIR)/cursor/%.mdc,$(RULE_TEMPLATES))

.PHONY: all scripts cursor install install-scripts install-cursor install-python check-vars clean test test-python lint fmt

all: check-vars scripts cursor ## Build generated files (default)

check-vars:
	@test -n "$(JIRA_ENDPOINT)" || \
	  (printf 'error: JIRA_ENDPOINT is required\nUsage: make JIRA_ENDPOINT=yourorg.atlassian.net [install]\n' >&2 && false)

scripts: check-vars $(SCRIPTS_GEN) ## Build scripts from .sh.in

$(BUILDDIR)/scripts/%.sh: scripts/%.sh.in | $(BUILDDIR)/scripts
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' -e 's|{{SCRIPT_DIR}}|$(SCRIPT_DIR)|g' $< > $@
	chmod +x $@

cursor: check-vars $(RULES_GEN) ## Build cursor rules from .mdc.in

$(BUILDDIR)/cursor/%.mdc: cursor/%.mdc.in | $(BUILDDIR)/cursor
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' -e 's|{{SCRIPT_DIR}}|$(SCRIPT_DIR)|g' $< > $@

$(BUILDDIR)/scripts $(BUILDDIR)/cursor:
	mkdir -p $@

install: all install-scripts install-cursor ## Build + copy to destinations

install-scripts: scripts
	install -d $(BINDIR)
	install -m 755 $(BUILDDIR)/scripts/* -t $(BINDIR)

install-cursor: cursor
	install -d $(RULESDIR) .cursor/rules
	install -m 644 $(BUILDDIR)/cursor/* -t $(RULESDIR)
	install -m 644 $(BUILDDIR)/cursor/* -t .cursor/rules

install-python: ## Sync Python venv via uv
	uv sync --all-extras

test: test-bats test-python ## Run all tests

test-bats: ## Run bats tests (requires built scripts)
	bats tests/*.bats

test-python: ## Run Python tests
	uv run pytest tests/ -v

lint: ## Run ruff linter and formatter check
	uv run ruff check notegraph/ tests/
	uv run ruff format --check notegraph/ tests/

fmt: ## Auto-format with ruff
	uv run ruff check --fix notegraph/ tests/
	uv run ruff format notegraph/ tests/

clean: ## Remove build directory and workspace rules
	rm -rf $(BUILDDIR) .cursor/rules/*.mdc
