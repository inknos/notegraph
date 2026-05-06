JIRA_ENDPOINT ?=
BUILDDIR      := build

# Template sources
AGENTS_TEMPLATE := cursor/AGENTS.md.in
RULE_TEMPLATES  := $(wildcard cursor/*.mdc.in)

# Build outputs
AGENTS_MD  := $(BUILDDIR)/AGENTS.md
RULES_GEN  := $(patsubst cursor/%.mdc.in,$(BUILDDIR)/cursor/%.mdc,$(RULE_TEMPLATES))

# Install destinations
OPENCODE_DIR := $(HOME)/.config/opencode
CLAUDE_DIR   := $(HOME)/.claude
SKILLS_SRC   := $(wildcard .cursor/skills/*)

.PHONY: all templates install install-agents install-skills install-python check-vars clean test test-python lint fmt docs man

all: check-vars templates ## Build generated files (default)

check-vars:
	@test -n "$(JIRA_ENDPOINT)" || \
	  (printf 'error: JIRA_ENDPOINT is required\nUsage: make JIRA_ENDPOINT=yourorg.atlassian.net [install]\n' >&2 && false)

templates: $(AGENTS_MD) $(RULES_GEN) ## Build AGENTS.md and cursor rules from templates

$(AGENTS_MD): $(AGENTS_TEMPLATE) | $(BUILDDIR)
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' $< > $@

$(BUILDDIR)/cursor/%.mdc: cursor/%.mdc.in | $(BUILDDIR)/cursor
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' $< > $@

$(BUILDDIR):
	mkdir -p $@

$(BUILDDIR)/cursor:
	mkdir -p $@

install: all install-agents install-skills install-python ## Build + install agents + skills + sync Python venv

install-agents: $(AGENTS_MD) ## Install AGENTS.md to OpenCode, Claude Code, and repo root
	install -Dm 644 $(AGENTS_MD) $(OPENCODE_DIR)/AGENTS.md
	install -Dm 644 $(AGENTS_MD) $(CLAUDE_DIR)/CLAUDE.md
	install -m 644 $(AGENTS_MD) AGENTS.md

install-skills: ## Install skills to OpenCode and Claude Code global dirs
	@for skill in $(SKILLS_SRC); do \
	  name=$$(basename $$skill); \
	  install -d $(OPENCODE_DIR)/skills/$$name; \
	  install -d $(CLAUDE_DIR)/skills/$$name; \
	  install -m 644 $$skill/* $(OPENCODE_DIR)/skills/$$name/; \
	  install -m 644 $$skill/* $(CLAUDE_DIR)/skills/$$name/; \
	done

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

clean: ## Remove build directory
	rm -rf $(BUILDDIR)
