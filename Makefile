.PHONY: install install-mcp mcp-github-server mcp-atlassian-server mcp-github-release-server mcp-unified-server mcp-list lint test check terraform-fmt-check terraform-validate verify-toolchain promptfoo-eval-pr promptfoo-eval-chatbot

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
TERRAFORM ?= terraform

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install ruff pytest

install-mcp:
	$(PYTHON) -m pip install -r requirements-mcp.txt

mcp-github-server:
	PYTHONPATH=src $(PYTHON) -m mcp_server.github_pr_server

mcp-atlassian-server:
	PYTHONPATH=src $(PYTHON) -m mcp_server.atlassian_context_server

mcp-github-release-server:
	PYTHONPATH=src $(PYTHON) -m mcp_server.github_release_ops_server

mcp-unified-server:
	PYTHONPATH=src $(PYTHON) -m mcp_server.unified_context_server

mcp-list:
	@echo "Available MCP servers:"
	@echo "  - make mcp-github-server         # PR intelligence tools"
	@echo "  - make mcp-github-release-server # tags/releases/compare tools"
	@echo "  - make mcp-atlassian-server      # Jira/Confluence tools"
	@echo "  - make mcp-unified-server        # GitHub + Atlassian context tools"

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

promptfoo-eval-pr:
	PROMPTFOO_AWS_REGION=$${PROMPTFOO_AWS_REGION:-us-gov-west-1} \
	PROMPTFOO_BEDROCK_MODEL_ID=$${PROMPTFOO_BEDROCK_MODEL_ID:-anthropic.claude-3-5-sonnet-20240620-v1:0} \
	npx promptfoo@latest eval --config evals/promptfoo/pr-review.promptfooconfig.yaml --output promptfoo-results/pr-review.json

promptfoo-eval-chatbot:
	PROMPTFOO_AWS_REGION=$${PROMPTFOO_AWS_REGION:-us-gov-west-1} \
	PROMPTFOO_BEDROCK_MODEL_ID=$${PROMPTFOO_BEDROCK_MODEL_ID:-anthropic.claude-3-5-sonnet-20240620-v1:0} \
	npx promptfoo@latest eval --config evals/promptfoo/chatbot-rag.promptfooconfig.yaml --output promptfoo-results/chatbot-rag.json

check: lint test
