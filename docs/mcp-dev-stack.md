# MCP Dev Stack: Podman + Kubernetes + EKS + Repo Context

This runbook shows how to configure a practical MCP stack for local dev and troubleshooting:

- `repo-unified` (this repository's MCP server)
- `podman` (container operations)
- `kubernetes` (`kubectl`-style cluster context)
- `eks-mcp` (Amazon EKS managed MCP endpoint)

## 1) Prerequisites

Run:

```bash
make install-mcp
make mcp-dev-check
```

One-command EC2 bootstrap (installs MCP deps and writes a ready config file):

```bash
make mcp-ec2-bootstrap
```

By default this writes:

- `~/mcp-servers.ec2.json`

Optional overrides:

```bash
AWS_REGION=us-east-1 AWS_PROFILE=default KUBECONFIG=~/.kube/config OUTPUT_FILE=~/mcp-servers.ec2.json make mcp-ec2-bootstrap
```

You should have:

- `python3` (or `.venv/bin/python`)
- `npx`
- `uvx`
- `aws` CLI
- `kubectl`
- `podman`

## 2) Add MCP client config

Use either:

- The generated file from `make mcp-ec2-bootstrap` (`~/mcp-servers.ec2.json`), or
- This config block in your MCP client settings (for example, Codex desktop MCP servers config):

```json
{
  "mcpServers": {
    "repo-unified": {
      "type": "stdio",
      "command": "/bin/zsh",
      "args": [
        "-lc",
        "cd '/Volumes/Crucial X10/GitHub/aws-agentic-ai-pr-reviewer' && make mcp-unified-server"
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
        "KUBECONFIG": "/Users/noahhouser/.kube/config"
      }
    },
    "eks-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws@latest",
        "https://eks-mcp.us-east-1.api.aws/mcp",
        "--service",
        "eks-mcp",
        "--region",
        "us-east-1",
        "--profile",
        "default",
        "--read-only"
      ]
    }
  }
}
```

Notes:

- Keep `readonly` / `--read-only` until you intentionally need write operations.
- If you use a different AWS profile/region, change `--profile` and `--region`.
- If your kubeconfig path differs, update `KUBECONFIG`.

## 3) How to call it

After MCP servers are configured and active, call them through prompts in this thread.

Examples:

1. `Use kubernetes MCP to list pods in namespace kube-system.`
2. `Use kubernetes MCP to describe deployment my-api in namespace prod.`
3. `Use eks-mcp to show cluster details for <cluster-name> in us-east-1.`
4. `Use podman MCP to list local containers and images.`
5. `Use repo-unified MCP to search Jira for release blockers and open PRs in owner/repo.`

## 4) Direct server commands (manual debugging)

If you want to run servers manually in terminals:

```bash
make mcp-unified-server
npx -y podman-mcp-server@latest
mcp-kubernetes --access-level readonly
uvx mcp-proxy-for-aws@latest https://eks-mcp.us-east-1.api.aws/mcp --service eks-mcp --region us-east-1 --profile default --read-only
```

## 5) Permission model recommendation

- Dev default: read-only everywhere.
- Enable write only per server when needed:
  - `kubernetes`: move to `readwrite` only for planned changes.
  - `eks-mcp`: remove `--read-only` only for controlled operations.
  - `podman`: keep local-only scopes and avoid host-destructive actions.
