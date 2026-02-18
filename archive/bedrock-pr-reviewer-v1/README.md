# Archive: bedrock-pr-reviewer-v1 Reference

> **⚠️ Reference Only — Do Not Deploy**
>
> The code in this directory was imported **solely as a reference** for prompt structure
> and review formatting conventions when designing the 2-stage planner/reviewer prompts.
>
> This code is **not used in production** and is not bundled into any Lambda deployment.
> The implementation in `src/worker/prompts/` is the authoritative version.

## Source

Original repository: [tmokmss/bedrock-pr-reviewer](https://github.com/tmokmss/bedrock-pr-reviewer) (v1 branch)

## What Was Referenced

- Output format structure (summary, severity, file+line annotations)
- Prompt instruction style for eliciting structured JSON from Claude
- "What I did not review" accountability section idea
- Evidence-first rule: never report a finding without citing code

## What Was NOT Copied

- No deployment code
- No infrastructure (CDK/CloudFormation)
- No authentication logic
- No complete prompt text was copied verbatim

All production prompts in `src/worker/prompts/` were written from scratch
following the architectural spec and incorporating lessons from the reference review.
