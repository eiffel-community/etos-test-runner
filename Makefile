# Makefile for etos-test-runner maintenance tasks.

UV ?= uv
# Lowest Python version supported at runtime. Used as the floor for the
# universal dependency resolution.
PYTHON_FLOOR ?= 3.11
LOCK := requirements.lock
# Scratch directory for the throwaway venvs used by lock-verify.
LOCK_VERIFY_DIR := .lock-verify

.PHONY: lock lock-verify

# Regenerate the dependency lock from pyproject.toml.
#
# requirements.lock pins the full transitive dependency closure with
# hashes so that installs are reproducible regardless of new releases of
# transitive dependencies. Regenerate deliberately (e.g. at release time
# or to pull in security updates), then commit the result.
lock:
	$(UV) pip compile pyproject.toml \
		--universal \
		--python-version $(PYTHON_FLOOR) \
		--generate-hashes \
		--no-annotate \
		-o $(LOCK)

# Verify that the committed lock actually installs etos-test-runner and its
# full dependency closure on every supported Python version, with hash
# verification. Fails if the lock is unbuildable/uninstallable or a locked
# version violates a specifier in pyproject.toml. Used by CI.
lock-verify:
	@set -e; \
	rm -rf $(LOCK_VERIFY_DIR); \
	for py in 3.11 3.13; do \
		echo "Installing etos-test-runner with the lock on Python $$py"; \
		$(UV) venv --python $$py $(LOCK_VERIFY_DIR)/venv-$$py >/dev/null; \
		VIRTUAL_ENV=$(LOCK_VERIFY_DIR)/venv-$$py $(UV) pip install -c $(LOCK) "etos_test_runner @ ." >/dev/null; \
	done; \
	rm -rf $(LOCK_VERIFY_DIR); \
	echo "Lock installs cleanly on all supported Python versions."
