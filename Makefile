.PHONY: install lint test check terraform-fmt-check terraform-validate verify-toolchain

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
TERRAFORM ?= terraform

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install ruff pytest

lint:
	$(PYTHON) -m ruff check src tests scripts

test:
	$(PYTHON) -m pytest -q

terraform-fmt-check:
	$(TERRAFORM) -chdir=infra/terraform fmt -check

terraform-validate:
	$(TERRAFORM) -chdir=infra/terraform init -backend=false -input=false
	$(TERRAFORM) -chdir=infra/terraform validate

verify-toolchain:
	$(PYTHON) scripts/predeploy_nonprod_checks.py --tfvars infra/terraform/terraform.nonprod.tfvars.example

check: lint test
