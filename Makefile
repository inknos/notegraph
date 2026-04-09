JIRA_ENDPOINT ?=
BINDIR        ?= $(HOME)/.local/bin
RULESDIR      ?= $(HOME)/.cursor/rules
SCRIPT_DIR    ?= $(CURDIR)/scripts

SCRIPT_TEMPLATES := scripts/jira-note.sh.in scripts/todo-page.sh.in
RULE_TEMPLATES   := $(wildcard cursor/*.mdc.in)

SCRIPTS_GEN := $(SCRIPT_TEMPLATES:.sh.in=.sh)
RULES_GEN   := $(patsubst cursor/%.mdc.in,.cursor/rules/%.mdc,$(RULE_TEMPLATES))

.PHONY: all scripts cursor install install-scripts install-cursor check-vars clean test

all: check-vars scripts cursor ## Build generated files in-repo (default)

check-vars:
	@test -n "$(JIRA_ENDPOINT)" || \
	  (printf 'error: JIRA_ENDPOINT is required\nUsage: make JIRA_ENDPOINT=yourorg.atlassian.net [install]\n' >&2 && false)

scripts: check-vars $(SCRIPTS_GEN) ## Build scripts from .sh.in

scripts/%.sh: scripts/%.sh.in
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' -e 's|{{SCRIPT_DIR}}|$(SCRIPT_DIR)|g' $< > $@
	chmod +x $@

cursor: check-vars $(RULES_GEN) ## Build cursor rules from .mdc.in

.cursor/rules/%.mdc: cursor/%.mdc.in | .cursor/rules
	sed -e 's|{{JIRA_ENDPOINT}}|$(JIRA_ENDPOINT)|g' -e 's|{{SCRIPT_DIR}}|$(SCRIPT_DIR)|g' $< > $@

.cursor/rules:
	mkdir -p $@

install: all install-scripts install-cursor ## Build + copy to destinations

install-scripts: scripts
	install -d $(BINDIR)
	install -m 755 scripts/gh-note.sh   $(BINDIR)/
	install -m 755 scripts/jira-note.sh $(BINDIR)/
	install -m 755 scripts/todo-page.sh $(BINDIR)/

install-cursor: cursor
	install -d $(RULESDIR)
	for f in $(RULES_GEN); do install -m 644 "$$f" $(RULESDIR)/; done

test: ## Run bats tests (requires built scripts)
	bats tests/

clean: ## Remove generated in-repo files
	rm -f $(SCRIPTS_GEN) $(RULES_GEN)
