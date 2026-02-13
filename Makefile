.PHONY: install lint test check

install:
	python3 -m pip install -r requirements.txt
	python3 -m pip install ruff

lint:
	python3 -m ruff check src tests scripts

test:
	python3 -m pytest -q

check: lint test
