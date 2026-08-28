# Used by CI (ubuntu-latest). Locally on Windows use `python tasks.py <target>`,
# which mirrors these exactly -- `make` is not installed on the dev machine.

.PHONY: test test-fast lint fmt freeze verify-sim verify-ledger demo-failure ingest

test:
	python -m pytest -v

test-fast:
	python -m pytest -q -m "not llm"

lint:
	python -m ruff check src tests

fmt:
	python -m ruff check --fix src tests

freeze:
	python -m recoup.simulator.freeze

verify-sim:
	python -m recoup.simulator.freeze --verify

verify-ledger:
	python -m recoup.cli verify-ledger

demo-failure:
	python -m recoup.cli demo-failure

ingest:
	python scripts/run_ingest.py
