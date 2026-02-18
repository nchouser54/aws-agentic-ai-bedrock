# PR Agent Evaluation Checklist

Use this checklist to systematically evaluate PR Agent against your existing Lambda-based reviewer over 2-4 weeks.

## Setup (Week 0)

- [ ] Add `OPENAI_KEY` to GitHub repository secrets
- [ ] Copy `.github/workflows/pr-agent-test.yml.example` to `.github/workflows/pr-agent-test.yml`
- [ ] Enable workflow and verify it runs on test PR
- [ ] Create evaluation spreadsheet to track metrics
- [ ] Identify 3-5 test repositories of varying sizes

## Evaluation Criteria

### 1. Review Quality

Test with 10-15 PRs across different categories:

#### Small PRs (1-5 files)
- [ ] PR #____ - Bug fix
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

- [ ] PR #____ - Feature addition
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

#### Medium PRs (6-20 files)
- [ ] PR #____ - Refactoring
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

- [ ] PR #____ - Multi-file feature
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

#### Large PRs (50+ files)
- [ ] PR #____ - Major feature
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

- [ ] PR #____ - Dependency update
  - **PR Agent found:** _______________
  - **Lambda found:** _______________
  - **Winner:** _______________

### 2. Speed Comparison

| PR # | Files | PR Agent Time | Lambda Time | Winner |
|------|-------|---------------|-------------|--------|
| ____ | ___   | ___ seconds   | ___ seconds | ____   |
| ____ | ___   | ___ seconds   | ___ seconds | ____   |
| ____ | ___   | ___ seconds   | ___ seconds | ____   |
| ____ | ___   | ___ seconds   | ___ seconds | ____   |
| ____ | ___   | ___ seconds   | ___ seconds | ____   |

**Average:**
- PR Agent: ___ seconds
- Lambda: ___ seconds

### 3. Cost Analysis

#### PR Agent (OpenAI)
- Model used: ________________
- PRs reviewed: ___
- Total OpenAI cost: $___
- Cost per PR: $___

#### Lambda System (Bedrock)
- Model used: ________________
- PRs reviewed: ___
- Total Bedrock cost: $___
- Lambda costs: $___
- Total cost: $___
- Cost per PR: $___

**Winner:** ________________

### 4. Comment Quality

Rate 1-5 (1=poor, 5=excellent) for each PR:

| PR # | PR Agent Clarity | Lambda Clarity | PR Agent Actionable | Lambda Actionable | PR Agent False Positives | Lambda False Positives |
|------|------------------|----------------|---------------------|-------------------|-------------------------|------------------------|
| ____ | ____/5          | ____/5         | ____/5             | ____/5            | ____/5                  | ____/5                 |
| ____ | ____/5          | ____/5         | ____/5             | ____/5            | ____/5                  | ____/5                 |
| ____ | ____/5          | ____/5         | ____/5             | ____/5            | ____/5                  | ____/5                 |

**Average Scores:**
- PR Agent Clarity: ____/5
- Lambda Clarity: ____/5
- PR Agent Actionable: ____/5
- Lambda Actionable: ____/5

### 5. Feature Coverage

| Feature | PR Agent | Lambda | Notes |
|---------|----------|--------|-------|
| Inline comments | ☐ | ☐ | Which is better? |
| Summary comments | ☐ | ☐ | |
| Security issues | ☐ | ☐ | |
| Performance issues | ☐ | ☐ | |
| Code style | ☐ | ☐ | |
| Documentation | ☐ | ☐ | |
| Error handling | ☐ | ☐ | |
| Test coverage | ☐ | ☐ | |
| Large PR handling | ☐ | ☐ | |

### 6. Developer Experience

Survey 3-5 developers after 2 weeks:

**Questions:**
1. Which reviewer's comments are more helpful? (PR Agent / Lambda / Equal)
2. Which reviewer has fewer false positives? (PR Agent / Lambda / Equal)
3. Which reviewer catches more real issues? (PR Agent / Lambda / Equal)
4. Which reviewer would you prefer to keep? (PR Agent / Lambda / Both / Neither)
5. Any specific feedback on either tool?

**Results:**
- Developer 1: ___________________________
- Developer 2: ___________________________
- Developer 3: ___________________________
- Developer 4: ___________________________
- Developer 5: ___________________________

### 7. Specific Issue Detection

Test with intentionally problematic code:

- [ ] **SQL Injection vulnerability**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

- [ ] **Memory leak**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

- [ ] **Race condition**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

- [ ] **Hardcoded credentials**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

- [ ] **Missing error handling**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

- [ ] **Performance inefficiency**
  - PR Agent detected: ☐ Yes ☐ No
  - Lambda detected: ☐ Yes ☐ No

### 8. Edge Cases

Test unusual scenarios:

- [ ] **Binary files in PR**
  - PR Agent handling: _______________
  - Lambda handling: _______________

- [ ] **Generated code (e.g., package-lock.json)**
  - PR Agent handling: _______________
  - Lambda handling: _______________

- [ ] **Very large file (5000+ lines)**
  - PR Agent handling: _______________
  - Lambda handling: _______________

- [ ] **Non-English comments**
  - PR Agent handling: _______________
  - Lambda handling: _______________

- [ ] **PR with 100+ files**
  - PR Agent handling: _______________
  - Lambda handling: _______________

## Patterns to Extract from PR Agent

Document specific patterns/techniques PR Agent uses that we should adopt:

### 1. PR Compression
- [ ] Analyzed PR Agent's compression strategy
- [ ] Documented approach: _______________
- [ ] Applicable to Lambda system: ☐ Yes ☐ No ☐ Partially
- [ ] Implementation complexity: ☐ Low ☐ Medium ☐ High

### 2. Prompt Engineering
- [ ] Reviewed PR Agent's prompts (if accessible)
- [ ] Key techniques observed: _______________
- [ ] Should adopt: _______________

### 3. Token Management
- [ ] Studied token budget allocation
- [ ] Techniques to borrow: _______________

### 4. Error Handling
- [ ] Reviewed failure modes
- [ ] Improvements for Lambda system: _______________

### 5. Configuration Approach
- [ ] Evaluated config file pattern
- [ ] Should we adopt .pr_agent.toml style? ☐ Yes ☐ No
- [ ] Alternative: _______________

## Final Decision (After 2-4 Weeks)

### Quantitative Summary

| Metric | PR Agent | Lambda | Winner |
|--------|----------|--------|--------|
| Avg Review Time | ___ sec | ___ sec | _____ |
| Cost per PR | $___ | $___ | _____ |
| Issues Found | ___ | ___ | _____ |
| False Positives | ___ | ___ | _____ |
| Developer Satisfaction | ___/5 | ___/5 | _____ |

### Qualitative Assessment

**PR Agent Strengths:**
1. _______________
2. _______________
3. _______________

**PR Agent Weaknesses:**
1. _______________
2. _______________
3. _______________

**Lambda System Strengths:**
1. _______________
2. _______________
3. _______________

**Lambda System Weaknesses:**
1. _______________
2. _______________
3. _______________

### Recommendation

Choose one:

- [ ] **Replace Lambda with PR Agent**
  - Rationale: _______________
  - Migration plan: _______________
  - Timeline: _______________

- [ ] **Keep Lambda, discontinue PR Agent**
  - Rationale: _______________
  - Patterns to borrow: _______________
  - Implementation plan: _______________

- [ ] **Run both in parallel**
  - Rationale: _______________
  - Use cases for each: _______________
  - Cost justification: _______________

- [ ] **Fork PR Agent and adapt**
  - Rationale: _______________
  - Effort estimate: _______________
  - Maintenance plan: _______________

- [ ] **Hybrid approach**
  - PR Agent for: _______________
  - Lambda for: _______________
  - Routing logic: _______________

### Next Steps

1. [ ] Share evaluation results with team
2. [ ] Get stakeholder buy-in on decision
3. [ ] Create implementation plan
4. [ ] Update documentation
5. [ ] Archive or remove test workflow
6. [ ] Implement chosen approach

## Notes

Use this space for additional observations, feedback, or considerations:

_______________________________________________________________________________
_______________________________________________________________________________
_______________________________________________________________________________
_______________________________________________________________________________
_______________________________________________________________________________
