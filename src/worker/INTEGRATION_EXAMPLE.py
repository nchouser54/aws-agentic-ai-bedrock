"""
Example: Integrating PR Agent Patterns into Existing Worker

This shows how to enhance src/worker/app.py with PR Agent's proven strategies
without deploying PR Agent itself. All changes are GovCloud-compatible.
"""

# ============================================================================
# STEP 1: Add Import to src/worker/app.py
# ============================================================================

# Add this near the top of the file:
from worker.pr_agent_patterns import (
    PRFileCompressor,
    PRAgentPromptBuilder,
    enhance_existing_review
)

# ============================================================================
# STEP 2: Enhance the review_pull_request() Function
# ============================================================================

def review_pull_request_enhanced(
    repo: str,
    pr_number: int,
    github_client,
    bedrock_client,
    review_mode: str = "comprehensive"
) -> dict:
    """
    Enhanced PR review using PR Agent compression and prompt strategies.
    
    This is a drop-in replacement for the existing review_pull_request() function.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 1. Fetch PR data (existing logic)
    pr_data = github_client.get_pull_request(repo, pr_number)
    files = github_client.get_pull_request_files(repo, pr_number)
    
    logger.info(
        f"Reviewing PR #{pr_number}: {pr_data['title']} "
        f"({len(files)} files, +{pr_data['additions']} -{pr_data['deletions']})"
    )
    
    # 2. Apply PR Agent compression (NEW)
    compressor = PRFileCompressor(max_tokens=32000)  # Claude 3.5 context
    
    # Filter and compress files
    compressed_files = compressor.compress_files(
        files=files,
        allow_truncation=True
    )
    
    if not compressed_files:
        logger.warning(f"No reviewable files in PR #{pr_number}")
        return {
            'summary': 'No code files to review (only config/generated files)',
            'findings': [],
            'score': 10
        }
    
    logger.info(
        f"Compressed {len(files)} -> {len(compressed_files)} files "
        f"for review"
    )
    
    # 3. Build improved prompt (NEW)
    prompt_builder = PRAgentPromptBuilder()
    prompt_data = prompt_builder.build_review_prompt(
        repo=repo,
        pr_number=pr_number,
        title=pr_data['title'],
        description=pr_data.get('body', ''),
        author=pr_data['user']['login'],
        files=compressed_files,
        additions=pr_data['additions'],
        deletions=pr_data['deletions']
    )
    
    # 4. Call Bedrock with improved prompt (existing client, new prompts)
    try:
        response = bedrock_client.invoke_model(
            system=prompt_data['system'],
            messages=[{
                'role': 'user',
                'content': prompt_data['prompt']
            }],
            temperature=0.3,  # Lower for more consistent reviews
            max_tokens=4096
        )
        
        # Parse JSON response
        import json
        review_result = json.loads(response)
        
        logger.info(
            f"Review complete: {len(review_result.get('findings', []))} findings, "
            f"score: {review_result.get('score', 'N/A')}"
        )
        
        return review_result
        
    except Exception as e:
        logger.error(f"Bedrock review failed: {e}", exc_info=True)
        raise


# ============================================================================
# STEP 3: Alternative - Minimal Changes to Existing Code
# ============================================================================

def minimal_enhancement_example():
    """
    Minimal changes if you want to keep existing structure.
    
    Just add file filtering and compression before sending to Bedrock.
    """
    
    # In your existing review_pull_request() function, add this:
    
    # BEFORE (your current code):
    # files = github_client.get_pull_request_files(repo, pr_number)
    # response = bedrock_client.generate_pr_review(files, pr_data)
    
    # AFTER (with compression):
    files = github_client.get_pull_request_files(repo, pr_number)
    
    # Add PR Agent compression
    from worker.pr_agent_patterns import PRFileCompressor
    compressor = PRFileCompressor(max_tokens=32000)
    compressed_files = compressor.compress_files(files, allow_truncation=True)
    
    # Use compressed files instead of all files
    response = bedrock_client.generate_pr_review(compressed_files, pr_data)


# ============================================================================
# STEP 4: Enhanced Bedrock Client Method (Optional)
# ============================================================================

# Add this to src/shared/bedrock_client.py:

def generate_pr_review_v2(
    self,
    repo: str,
    pr_number: int,
    title: str,
    description: str,
    author: str,
    files: list[dict],
    additions: int,
    deletions: int,
    temperature: float = 0.3
) -> dict:
    """
    Generate PR review using PR Agent-style prompts.
    
    This is a new method that uses the improved prompt structure.
    Your existing generate_pr_review() method remains unchanged.
    """
    from worker.pr_agent_patterns import PRAgentPromptBuilder
    
    # Build structured prompt
    builder = PRAgentPromptBuilder()
    prompt_data = builder.build_review_prompt(
        repo=repo,
        pr_number=pr_number,
        title=title,
        description=description,
        author=author,
        files=files,
        additions=additions,
        deletions=deletions
    )
    
    # Call Bedrock
    response = self.invoke_model(
        system=prompt_data['system'],
        messages=[{
            'role': 'user',
            'content': prompt_data['prompt']
        }],
        temperature=temperature,
        max_tokens=4096
    )
    
    # Parse and return
    import json
    return json.loads(response)


# ============================================================================
# STEP 5: Add Unit Tests
# ============================================================================

# Create tests/test_pr_agent_patterns.py:

import pytest
from worker.pr_agent_patterns import PRFileCompressor, PRAgentPromptBuilder


def test_should_review_file():
    """Test file filtering logic."""
    compressor = PRFileCompressor()
    
    # Should review
    assert compressor.should_review_file('src/app.py') is True
    assert compressor.should_review_file('lib/auth.js') is True
    assert compressor.should_review_file('infra/main.tf') is True
    
    # Should skip
    assert compressor.should_review_file('package-lock.json') is False
    assert compressor.should_review_file('dist/bundle.min.js') is False
    assert compressor.should_review_file('image.png') is False


def test_file_scoring():
    """Test file priority scoring."""
    compressor = PRFileCompressor()
    
    # Modified Python file should score high
    file_data = {
        'filename': 'src/auth.py',
        'status': 'modified',
        'changes': 50,
        'patch': 'some diff'
    }
    score = compressor.score_file(file_data)
    assert score.score > 10  # Base score + Python bonus
    
    # Test file should be lower priority
    test_file = {
        'filename': 'tests/test_auth.py',
        'status': 'modified',
        'changes': 30,
        'patch': 'test diff'
    }
    test_score = compressor.score_file(test_file)
    assert test_score.score < score.score


def test_compression():
    """Test file compression within token budget."""
    compressor = PRFileCompressor(max_tokens=1000)
    
    files = [
        {
            'filename': 'src/app.py',
            'status': 'modified',
            'changes': 10,
            'patch': 'a' * 2000  # ~500 tokens
        },
        {
            'filename': 'src/lib.py',
            'status': 'modified',
            'changes': 10,
            'patch': 'b' * 2000  # ~500 tokens
        },
        {
            'filename': 'src/util.py',
            'status': 'modified',
            'changes': 10,
            'patch': 'c' * 2000  # ~500 tokens
        }
    ]
    
    compressed = compressor.compress_files(files)
    
    # Should fit within budget (first 2 files)
    assert len(compressed) <= 2
    
    # Total tokens should be under budget
    total_tokens = sum(len(f['patch']) // 4 for f in compressed)
    assert total_tokens <= 1000


def test_prompt_building():
    """Test prompt structure."""
    builder = PRAgentPromptBuilder()
    
    files = [{
        'filename': 'src/app.py',
        'status': 'modified',
        'changes': 10,
        'patch': '--- a/src/app.py\n+++ b/src/app.py\n@@ some diff',
        'score': 15.0
    }]
    
    prompt = builder.build_review_prompt(
        repo='owner/repo',
        pr_number=123,
        title='Add feature',
        description='This adds a feature',
        author='developer',
        files=files,
        additions=10,
        deletions=5
    )
    
    # Check structure
    assert 'system' in prompt
    assert 'prompt' in prompt
    assert 'Security' in prompt['prompt']
    assert 'Performance' in prompt['prompt']
    assert 'src/app.py' in prompt['prompt']


# ============================================================================
# STEP 6: Deployment - Update Lambda Environment Variables
# ============================================================================

# Add to infra/terraform/main.tf:

resource "aws_lambda_function" "worker" {
  # ... existing configuration ...
  
  environment {
    variables = {
      # Existing variables
      BEDROCK_MODEL_ID = var.bedrock_model_id
      
      # New: Enable PR Agent patterns
      PR_COMPRESSION_ENABLED = "true"
      PR_MAX_TOKENS          = "32000"  # Claude 3.5 context window
      PR_IMPROVED_PROMPTS    = "true"
      
      # New: File filtering
      PR_SKIP_LOCK_FILES     = "true"
      PR_SKIP_GENERATED      = "true"
      PR_SKIP_TESTS          = "false"  # Still review tests, just lower priority
    }
  }
}


# ============================================================================
# STEP 7: Feature Flag Implementation
# ============================================================================

# Add to src/worker/app.py to gradually roll out:

import os

def get_review_configuration() -> dict:
    """Get review configuration from environment."""
    return {
        'compression_enabled': os.getenv('PR_COMPRESSION_ENABLED', 'true').lower() == 'true',
        'max_tokens': int(os.getenv('PR_MAX_TOKENS', '32000')),
        'improved_prompts': os.getenv('PR_IMPROVED_PROMPTS', 'true').lower() == 'true',
        'skip_lock_files': os.getenv('PR_SKIP_LOCK_FILES', 'true').lower() == 'true'
    }


def review_pull_request_with_feature_flags(
    repo: str,
    pr_number: int,
    github_client,
    bedrock_client
) -> dict:
    """Review with optional PR Agent enhancements (feature flagged)."""
    config = get_review_configuration()
    
    # Fetch PR data
    pr_data = github_client.get_pull_request(repo, pr_number)
    files = github_client.get_pull_request_files(repo, pr_number)
    
    # Optionally compress files
    if config['compression_enabled']:
        from worker.pr_agent_patterns import PRFileCompressor
        compressor = PRFileCompressor(max_tokens=config['max_tokens'])
        files = compressor.compress_files(files)
    
    # Use improved or legacy prompts
    if config['improved_prompts']:
        from worker.pr_agent_patterns import PRAgentPromptBuilder
        builder = PRAgentPromptBuilder()
        prompt_data = builder.build_review_prompt(
            repo=repo,
            pr_number=pr_number,
            title=pr_data['title'],
            description=pr_data.get('body', ''),
            author=pr_data['user']['login'],
            files=files,
            additions=pr_data['additions'],
            deletions=pr_data['deletions']
        )
        review = bedrock_client.invoke_with_custom_prompt(
            system=prompt_data['system'],
            prompt=prompt_data['prompt']
        )
    else:
        # Use existing/legacy prompt logic
        review = bedrock_client.generate_pr_review(files, pr_data)
    
    return review


# ============================================================================
# STEP 8: Monitoring and Metrics
# ============================================================================

# Add CloudWatch metrics to track improvements:

import boto3

cloudwatch = boto3.client('cloudwatch', region_name='us-gov-west-1')

def log_compression_metrics(
    original_file_count: int,
    compressed_file_count: int,
    original_tokens: int,
    compressed_tokens: int
):
    """Log compression metrics to CloudWatch."""
    cloudwatch.put_metric_data(
        Namespace='PRReviewer/Compression',
        MetricData=[
            {
                'MetricName': 'FilesCompressed',
                'Value': original_file_count - compressed_file_count,
                'Unit': 'Count'
            },
            {
                'MetricName': 'TokensSaved',
                'Value': original_tokens - compressed_tokens,
                'Unit': 'Count'
            },
            {
                'MetricName': 'CompressionRatio',
                'Value': compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
                'Unit': 'Percent'
            }
        ]
    )


# ============================================================================
# STEP 9: Rollout Plan
# ============================================================================

"""
Gradual Rollout Strategy:

Week 1: Deploy with feature flags OFF
- Deploy code to Lambda
- Verify no regressions
- PR_COMPRESSION_ENABLED=false
- PR_IMPROVED_PROMPTS=false

Week 2: Enable compression only
- PR_COMPRESSION_ENABLED=true
- Monitor token usage (should decrease)
- Monitor review quality (should be same or better)
- Check CloudWatch metrics

Week 3: Enable improved prompts
- PR_IMPROVED_PROMPTS=true
- Compare review quality with baseline
- Collect feedback from team
- Monitor Bedrock costs (should decrease due to compression)

Week 4: Full adoption
- Make new behavior default
- Update documentation
- Train team on new review format
- Remove feature flags (always-on)

Success Metrics:
- Token usage: down 30-50%
- Review quality: same or better (survey team)
- Bedrock costs: down 20-40%
- Review latency: same or faster
"""


# ============================================================================
# Summary: What Changes in Your Code
# ============================================================================

"""
MINIMAL CHANGES REQUIRED:

1. Add new file: src/worker/pr_agent_patterns.py (from previous artifact)
2. Add 3 lines to src/worker/app.py:
   - Import: from worker.pr_agent_patterns import PRFileCompressor
   - Before Bedrock call: compressor = PRFileCompressor(max_tokens=32000)
   - Compress files: compressed = compressor.compress_files(files)

3. Add 3 environment variables to Lambda:
   - PR_COMPRESSION_ENABLED=true
   - PR_MAX_TOKENS=32000
   - PR_IMPROVED_PROMPTS=true

That's it! No API changes, no new services, no PR Agent deployment.

BENEFITS:
- Reduce Bedrock token usage by 30-50%
- Better file prioritization (security > tests)
- Skip irrelevant files (lock files, generated code)
- Improved prompt structure (categories, JSON output)
- Feature-flagged for safe rollout
- Zero infrastructure changes
- GovCloud-compatible (no external APIs)
"""
