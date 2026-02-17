"""
PR Agent Compression and Filtering Patterns for GovCloud.

This module extracts proven patterns from qodo-ai/pr-agent for use with Bedrock.
No external dependencies - integrates with existing bedrock_client.py.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FileScore:
    """Scoring for PR file prioritization."""
    filename: str
    score: float
    changes: int
    patch: str
    status: str
    estimated_tokens: int


class PRFileCompressor:
    """
    Compress PR files to fit within token limits using PR Agent strategies.
    Based on: pr-agent/pr_agent/algo/pr_processing.py
    """
    
    # Files/patterns to skip during review (PR Agent's approach)
    SKIP_PATTERNS = {
        # Lock files
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'Pipfile.lock', 'poetry.lock', 'Gemfile.lock',
        'go.sum', 'Cargo.lock', 'composer.lock',
        
        # Minified files
        '.min.js', '.min.css', '.bundle.js',
        
        # Build artifacts
        'dist/', 'build/', 'target/', 'out/', '.next/',
        'node_modules/', 'vendor/', '__pycache__/',
        
        # Generated files
        'generated', '-generated.', 'gen/', '.pb.go', '.pb.py',
        
        # Binary/media files
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg',
        '.woff', '.woff2', '.ttf', '.eot', '.otf',
        '.pdf', '.zip', '.tar', '.gz', '.mp4', '.mp3',
        
        # Documentation (usually reviewed differently)
        'CHANGELOG.md', 'CHANGELOG.rst',
        
        # Database migrations (too specific)
        'migrations/', 'migrate/', 'alembic/',
        
        # Large data files
        '.csv', '.json', '.xml', '.sql' 
    }
    
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', 
        '.rb', '.php', '.rs', '.cpp', '.c', '.cc', '.h', '.hpp',
        '.cs', '.swift', '.kt', '.kts', '.scala', '.sh', '.bash',
        '.yaml', '.yml', '.toml', '.tf', '.hcl'
    }
    
    def __init__(self, max_tokens: int = 32000):
        """
        Initialize compressor.
        
        Args:
            max_tokens: Maximum tokens to use for all files combined
        """
        self.max_tokens = max_tokens
    
    def should_review_file(self, filename: str) -> bool:
        """
        Determine if a file should be reviewed.
        
        Args:
            filename: Path to the file
            
        Returns:
            True if file should be reviewed
        """
        filename_lower = filename.lower()
        
        # Skip if matches any skip pattern
        if any(pattern in filename_lower for pattern in self.SKIP_PATTERNS):
            logger.debug(f"Skipping {filename}: matches skip pattern")
            return False
        
        # Must have code extension
        if not any(filename.endswith(ext) for ext in self.CODE_EXTENSIONS):
            logger.debug(f"Skipping {filename}: not a code file")
            return False
        
        return True
    
    def score_file(self, file_data: Dict[str, Any]) -> FileScore:
        """
        Score a file for review priority (PR Agent scoring strategy).
        
        Higher scores = higher priority to include in review.
        
        Args:
            file_data: GitHub API file data with keys:
                - filename: str
                - status: 'added'|'modified'|'removed'
                - changes: int
                - patch: str (unified diff)
        
        Returns:
            FileScore object
        """
        filename = file_data['filename']
        status = file_data.get('status', 'modified')
        changes = file_data.get('changes', 0)
        patch = file_data.get('patch', '')
        
        score = 0.0
        
        # 1. Prioritize by change type
        if status == 'modified':
            score += 10.0  # Modified files most important
        elif status == 'added':
            score += 7.0   # New files important but less than modifications
        elif status == 'removed':
            score += 2.0   # Deletions less important
        
        # 2. Prioritize by file type
        if filename.endswith('.py'):
            score += 5.0  # Python (our main language)
        elif filename.endswith(('.js', '.ts', '.tsx', '.jsx')):
            score += 4.0  # JavaScript/TypeScript
        elif filename.endswith('.yaml') or filename.endswith('.yml'):
            score += 3.0  # Config files important for infra
        elif filename.endswith('.tf'):
            score += 4.0  # Terraform very important
        
        # 3. Penalize test files (review but lower priority)
        if 'test_' in filename or '_test.' in filename or '/tests/' in filename:
            score -= 3.0
        
        # 4. Penalize very large files (hard to review, often generated)
        if changes > 500:
            score -= 5.0
        elif changes > 1000:
            score -= 10.0
        
        # 5. Boost critical security files
        security_patterns = ['auth', 'security', 'secrets', 'credentials', 'password']
        if any(pattern in filename.lower() for pattern in security_patterns):
            score += 8.0
        
        # 6. Boost core business logic
        if '/src/' in filename and not 'test' in filename:
            score += 3.0
        
        # Estimate tokens (rough: 4 chars per token)
        estimated_tokens = len(patch) // 4
        
        return FileScore(
            filename=filename,
            score=score,
            changes=changes,
            patch=patch,
            status=status,
            estimated_tokens=estimated_tokens
        )
    
    def compress_files(
        self,
        files: List[Dict[str, Any]],
        allow_truncation: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Compress PR files to fit within token budget.
        
        Strategy (from PR Agent):
        1. Filter out non-reviewable files
        2. Score remaining files by importance
        3. Sort by score (highest first)
        4. Take as many as fit within token budget
        5. Optionally truncate last file if needed
        
        Args:
            files: List of GitHub API file objects
            allow_truncation: If True, truncate last file to fit budget
            
        Returns:
            Compressed list of files that fit within token budget
        """
        # 1. Filter non-reviewable files
        reviewable = [f for f in files if self.should_review_file(f['filename'])]
        
        logger.info(
            f"Filtered {len(files)} files -> {len(reviewable)} reviewable "
            f"({len(files) - len(reviewable)} skipped)"
        )
        
        if not reviewable:
            return []
        
        # 2. Score all files
        scored = [self.score_file(f) for f in reviewable]
        
        # 3. Sort by score (descending)
        scored.sort(key=lambda x: x.score, reverse=True)
        
        # 4. Select files within token budget
        compressed = []
        tokens_used = 0
        
        for file_score in scored:
            if tokens_used + file_score.estimated_tokens <= self.max_tokens:
                # File fits completely
                compressed.append({
                    'filename': file_score.filename,
                    'status': file_score.status,
                    'changes': file_score.changes,
                    'patch': file_score.patch,
                    'score': file_score.score
                })
                tokens_used += file_score.estimated_tokens
                
            elif len(compressed) == 0 and allow_truncation:
                # At least include first file (truncated)
                logger.warning(
                    f"Truncating {file_score.filename} to fit token budget "
                    f"({file_score.estimated_tokens} -> {self.max_tokens - tokens_used})"
                )
                
                max_chars = (self.max_tokens - tokens_used) * 4
                truncated_patch = file_score.patch[:max_chars]
                
                compressed.append({
                    'filename': file_score.filename,
                    'status': file_score.status,
                    'changes': file_score.changes,
                    'patch': truncated_patch + "\n\n[... truncated due to size ...]",
                    'score': file_score.score,
                    'truncated': True
                })
                break
        
        logger.info(
            f"Compressed {len(reviewable)} files -> {len(compressed)} files "
            f"(~{tokens_used} tokens / {self.max_tokens} budget)"
        )
        
        # Log what was excluded
        excluded_count = len(reviewable) - len(compressed)
        if excluded_count > 0:
            excluded_files = [s.filename for s in scored[len(compressed):]]
            logger.info(f"Excluded {excluded_count} files: {', '.join(excluded_files[:5])}")
        
        return compressed


class PRAgentPromptBuilder:
    """
    Build improved prompts using PR Agent strategies.
    Based on: pr-agent/pr_agent/settings/pr_reviewer_prompts.toml
    """
    
    SYSTEM_PROMPT = """You are an expert code reviewer with deep knowledge of:
- Security vulnerabilities and secure coding practices
- Performance optimization and scalability patterns
- Code quality, maintainability, and best practices
- Testing strategies and coverage requirements
- Language-specific idioms and common pitfalls

Your reviews are:
- Concise and actionable (specific line numbers and fix suggestions)
- Prioritized by severity (critical security issues first)
- Constructive and professional in tone
- Focused on real issues (not nitpicking style)
"""
    
    REVIEW_PROMPT_TEMPLATE = """
# Code Review Task

## Pull Request Information
- **Repository:** {repo}
- **PR #{pr_number}:** {title}
- **Author:** {author}
- **Files Changed:** {files_changed}
- **Lines Changed:** +{additions} -{deletions}

## Context
{description}

## Changes to Review
{file_changes}

---

## Review Instructions

Analyze the code changes and provide feedback in these categories:

### 1. 🔒 Security
- Hardcoded secrets, API keys, passwords
- SQL injection, command injection, XSS vulnerabilities
- Authentication/authorization bypasses
- Insecure cryptography or data handling
- Exposure of sensitive data in logs/errors

### 2. ⚡ Performance
- N+1 query problems
- Inefficient algorithms or data structures
- Memory leaks or resource leaks
- Unnecessary API calls or database queries
- Missing caching opportunities

### 3. 🐛 Correctness
- Logic errors or edge cases
- Race conditions or concurrency issues
- Error handling missing or incorrect
- Null/undefined handling issues
- Type safety violations

### 4. 🧪 Testing
- Missing test coverage for new code
- Tests not covering edge cases
- Tests that are brittle or flaky
- Missing integration tests

### 5. 📋 Best Practices
- Code duplication (DRY violations)
- Poor naming (unclear variables/functions)
- Overly complex code (could be simplified)
- Missing documentation for complex logic
- Inconsistent with codebase patterns

---

## Output Format

Provide your review as a JSON object:

```json
{{
  "summary": "1-2 sentence overall assessment",
  "score": 7,  // 1-10 scale (10=perfect, 1=major issues)
  "findings": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "critical",  // critical|high|medium|low
      "category": "security",  // security|performance|correctness|testing|practices
      "title": "Brief issue description",
      "issue": "Detailed explanation of the problem",
      "suggestion": "Specific code change to fix it"
    }}
  ]
}}
```

### Guidelines:
- Only include real issues (not minor style suggestions)
- At least 3 findings (unless code is perfect)
- Provide specific line numbers
- Give concrete fix suggestions (code examples when helpful)
- Prioritize by severity
- Be constructive and professional

Begin your review now.
"""
    
    def build_review_prompt(
        self,
        repo: str,
        pr_number: int,
        title: str,
        description: str,
        author: str,
        files: List[Dict[str, Any]],
        additions: int,
        deletions: int
    ) -> dict:
        """
        Build a structured prompt for PR review.
        
        Args:
            repo: Repository name (owner/repo)
            pr_number: PR number
            title: PR title
            description: PR description/body
            author: PR author username
            files: List of compressed file changes
            additions: Total lines added
            deletions: Total lines deleted
            
        Returns:
            Dict with 'system' and 'prompt' keys for Bedrock
        """
        # Format file changes for prompt
        file_changes_parts = []
        for idx, f in enumerate(files, 1):
            file_changes_parts.append(
                f"### File {idx}: `{f['filename']}` ({f['status'].upper()}, {f['changes']} changes)\n\n"
                f"```diff\n{f['patch']}\n```\n"
            )
        
        file_changes_text = "\n".join(file_changes_parts)
        
        # Build full prompt
        prompt = self.REVIEW_PROMPT_TEMPLATE.format(
            repo=repo,
            pr_number=pr_number,
            title=title,
            description=description or "(no description provided)",
            author=author,
            files_changed=len(files),
            additions=additions,
            deletions=deletions,
            file_changes=file_changes_text
        )
        
        return {
            'system': self.SYSTEM_PROMPT,
            'prompt': prompt
        }


def enhance_existing_review(
    files: List[Dict[str, Any]],
    max_tokens: int = 32000
) -> tuple[List[Dict[str, Any]], dict]:
    """
    Drop-in enhancement for existing worker review logic.
    
    This function:
    1. Compresses files using PR Agent strategy
    2. Builds improved prompts
    3. Returns data ready for BedrockClient
    
    Usage in src/worker/app.py:
        from worker.pr_agent_patterns import enhance_existing_review
        
        # In review_pull_request() function:
        compressed_files, prompt_data = enhance_existing_review(
            files=pr_files,
            max_tokens=32000
        )
        
        response = bedrock_client.generate_pr_review(
            system_prompt=prompt_data['system'],
            user_prompt=prompt_data['prompt']
        )
    
    Args:
        files: List of GitHub API file objects
        max_tokens: Maximum tokens for compressed files
        
    Returns:
        Tuple of (compressed_files, prompt_components)
    """
    compressor = PRFileCompressor(max_tokens=max_tokens)
    compressed = compressor.compress_files(files, allow_truncation=True)
    
    # Extract metadata for prompt
    total_additions = sum(f.get('additions', 0) for f in files)
    total_deletions = sum(f.get('deletions', 0) for f in files)
    
    # Return compressed files and prompt builder helper
    return compressed, {
        'additions': total_additions,
        'deletions': total_deletions,
        'system_prompt': PRAgentPromptBuilder.SYSTEM_PROMPT
    }


# Example usage
if __name__ == "__main__":
    # Example PR files
    example_files = [
        {
            'filename': 'src/app.py',
            'status': 'modified',
            'changes': 50,
            'additions': 30,
            'deletions': 20,
            'patch': '--- a/src/app.py\n+++ b/src/app.py\n@@ ...'
        },
        {
            'filename': 'package-lock.json',
            'status': 'modified',
            'changes': 5000,
            'patch': '...'
        }
    ]
    
    # Compress
    compressor = PRFileCompressor(max_tokens=10000)
    compressed = compressor.compress_files(example_files)
    
    print(f"Compressed {len(example_files)} files -> {len(compressed)} files")
    
    # Build prompt
    builder = PRAgentPromptBuilder()
    prompt_data = builder.build_review_prompt(
        repo="owner/repo",
        pr_number=123,
        title="Add new feature",
        description="This PR adds...",
        author="developer",
        files=compressed,
        additions=30,
        deletions=20
    )
    
    print(f"\nSystem prompt length: {len(prompt_data['system'])} chars")
    print(f"User prompt length: {len(prompt_data['prompt'])} chars")
