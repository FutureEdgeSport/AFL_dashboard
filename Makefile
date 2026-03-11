# AFL Dashboard – Makefile
# ========================
# Common tasks for development and CI.

.PHONY: test test-quick lint update dry-run setup-hooks clean

# Default Python (prefer .venv)
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# ── Tests ──────────────────────────────────────────────────────
test:  ## Run the full integration test suite
	$(PYTHON) -m pytest tests/ -v --tb=short

test-quick:  ## Run tests without slow markers
	$(PYTHON) -m pytest tests/ -v --tb=short -m "not slow"

# ── Linting ────────────────────────────────────────────────────
lint:  ## Basic syntax check on key modules
	$(PYTHON) -m py_compile app.py
	$(PYTHON) -m py_compile scheduled_update.py
	$(PYTHON) -m py_compile data_loader.py
	@echo "✓ All key modules compile cleanly"

# ── Pipeline ───────────────────────────────────────────────────
update:  ## Run the full scheduled update pipeline
	$(PYTHON) scheduled_update.py

dry-run:  ## Show what the pipeline would do without executing
	$(PYTHON) scheduled_update.py --dry-run

# ── Git hooks ──────────────────────────────────────────────────
setup-hooks:  ## Install git pre-push hook that runs tests
	@mkdir -p .git/hooks
	@echo '#!/bin/sh' > .git/hooks/pre-push
	@echo '# Auto-run tests before pushing' >> .git/hooks/pre-push
	@echo 'echo "Running tests before push..."' >> .git/hooks/pre-push
	@echo 'make test-quick || { echo "Tests failed — push aborted."; exit 1; }' >> .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "✓ Installed pre-push hook → .git/hooks/pre-push"

# ── Housekeeping ───────────────────────────────────────────────
clean:  ## Remove temp/backup files
	rm -rf data/backups/*.tmp __pycache__ tests/__pycache__ utils/__pycache__
	@echo "✓ Cleaned temp files"

# ── Help ───────────────────────────────────────────────────────
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'
