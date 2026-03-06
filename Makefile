.PHONY: test-smoke test-fast test-all-fast test-full test-domain

test-smoke:
	./scripts/test-suite.sh smoke

test-fast:
	./scripts/test-suite.sh fast

test-all-fast:
	./scripts/test-suite.sh all-fast

test-full:
	./scripts/test-suite.sh full

test-domain:
	@if [ -z "$(DOMAIN)" ]; then echo "Usage: make test-domain DOMAIN=<domain>"; exit 1; fi
	./scripts/test-suite.sh domain "$(DOMAIN)"
