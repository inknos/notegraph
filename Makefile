JIRA_ENDPOINT ?=
BINDIR        ?= $(HOME)/.local/bin
RULESDIR      ?= $(HOME)/.cursor/rules
SCRIPT_DIR    ?= $(CURDIR)/scripts
BUILDDIR      := build

SCRIPT_TEMPLATES := scripts/jira-note.sh.in scripts/todo-page.sh.in
RULE_TEMPLATES   := $(wildcard cursor/*.mdc.in)

SCRIPTS_GEN := $(patsubst scripts/%.sh.in,$(BUILDDIR)/scripts/%.sh,$(SCRIPT_TEMPLATES))
RULES_GEN   := $(patsubst cursor/%.mdc.in,$(BUILDDIR)/cursor/%.mdc,$(RULE_TEMPLATES))

.PHONY: all scripts cursor install install-scripts install-cursor check-vars clean test

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
	install -m 755 scripts/gh-note.sh $(BINDIR)/

install-cursor: cursor
	install -d $(RULESDIR)

test: ## Run bats tests (requires built scripts)
	bats tests/

clean: ## Remove build directory
	rm -rf $(BUILDDIR)
