.PHONY: install run test lint check
install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.lock
	.venv/bin/python -m pip install --no-deps -e .
run:
	.venv/bin/clearledger
test:
	.venv/bin/python -m pytest -q
lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
check: lint test
