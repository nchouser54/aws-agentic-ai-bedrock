#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/config}"
OUTPUT_FILE="${OUTPUT_FILE:-$HOME/mcp-servers.ec2.json}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --repo-dir <path>       Repository path (default: ${REPO_DIR})
  --aws-region <region>   AWS region for EKS MCP (default: ${AWS_REGION})
  --aws-profile <profile> AWS profile for EKS MCP (default: ${AWS_PROFILE})
  --kubeconfig <path>     kubeconfig path for kubernetes MCP (default: ${KUBECONFIG_PATH})
  --output <path>         Output MCP config file (default: ${OUTPUT_FILE})
  -h, --help              Show this help

Environment overrides:
  REPO_DIR, AWS_REGION, AWS_PROFILE, KUBECONFIG, OUTPUT_FILE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-dir)
      REPO_DIR="$2"
      shift 2
      ;;
    --aws-region)
      AWS_REGION="$2"
      shift 2
      ;;
    --aws-profile)
      AWS_PROFILE="$2"
      shift 2
      ;;
    --kubeconfig)
      KUBECONFIG_PATH="$2"
      shift 2
      ;;
    --output)
      OUTPUT_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

echo "[1/5] Validating base tools..."
for cmd in python3 npm npx aws kubectl podman; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    echo "Install ${cmd} first, then re-run." >&2
    exit 1
  fi
done

if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Repository directory not found: ${REPO_DIR}" >&2
  exit 1
fi

cd "${REPO_DIR}"

echo "[2/5] Installing repo MCP Python dependencies..."
if [[ ! -x "${REPO_DIR}/.venv/bin/python" ]]; then
  python3 -m venv .venv
fi
"${REPO_DIR}/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"${REPO_DIR}/.venv/bin/python" -m pip install -r requirements-mcp.txt >/dev/null

echo "[3/5] Installing MCP CLI helpers..."
npm install -g @azure/mcp-kubernetes >/dev/null

if ! command -v uvx >/dev/null 2>&1; then
  "${REPO_DIR}/.venv/bin/python" -m pip install uv >/dev/null
  if [[ -x "${HOME}/.local/bin/uvx" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "uvx is still unavailable after installation attempt." >&2
  echo "Install uv manually, then re-run." >&2
  exit 1
fi

echo "[4/5] Running MCP dev stack checks..."
make mcp-dev-check

echo "[5/5] Writing MCP config to ${OUTPUT_FILE}..."
mkdir -p "$(dirname "${OUTPUT_FILE}")"
cat > "${OUTPUT_FILE}" <<EOF
{
  "mcpServers": {
    "repo-unified": {
      "type": "stdio",
      "command": "/bin/zsh",
      "args": [
        "-lc",
        "cd '${REPO_DIR}' && make mcp-unified-server"
      ]
    },
    "podman": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "podman-mcp-server@latest"]
    },
    "kubernetes": {
      "type": "stdio",
      "command": "mcp-kubernetes",
      "args": ["--access-level", "readonly"],
      "env": {
        "KUBECONFIG": "${KUBECONFIG_PATH}"
      }
    },
    "eks-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://eks-mcp.${AWS_REGION}.api.aws/mcp",
        "--service",
        "eks-mcp",
        "--region",
        "${AWS_REGION}",
        "--profile",
        "${AWS_PROFILE}",
        "--read-only"
      ]
    }
  }
}
EOF

cat <<EOF

Completed.

Next steps:
1. Import ${OUTPUT_FILE} into your MCP client config.
2. Set app creds for repo MCP tools before using Atlassian/GitHub tool calls:
   export GITHUB_APP_IDS_SECRET_ARN=<secret-arn>
   export GITHUB_APP_PRIVATE_KEY_SECRET_ARN=<secret-arn>
   export ATLASSIAN_CREDENTIALS_SECRET_ARN=<secret-arn>
3. Restart your MCP client and test:
   - Use kubernetes MCP to list pods in namespace kube-system.
   - Use eks-mcp to show cluster details for <cluster-name>.
   - Use podman MCP to list containers.

EOF
