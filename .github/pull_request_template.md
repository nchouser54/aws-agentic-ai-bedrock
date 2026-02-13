## Summary

- What changed?
- Why was this change needed?

## Scope

- [ ] Core PR reviewer
- [ ] Chatbot / Teams
- [ ] KB sync
- [ ] Release notes
- [ ] Sprint report
- [ ] Test generation
- [ ] PR description
- [ ] Terraform / IaC
- [ ] Docs / runbooks
- [ ] CI / quality gates

## Validation

- [ ] `ruff check src tests scripts`
- [ ] `pytest -q`
- [ ] `terraform fmt -check` (if IaC changed)
- [ ] `terraform validate` (if IaC changed)

## PR Title Convention

Use a scoped title that reflects shipped impact (this becomes the squash commit subject):

- `feat(scope): short outcome`
- `fix(scope): short outcome`
- `chore(scope): short outcome`

Examples:

- `feat(reviewer): add Jira enrichment for ticket-aware findings`
- `feat(platform): add sprint report, test-gen, and PR description agents`
- `chore(ci): add lint/test and terraform quality gates`
