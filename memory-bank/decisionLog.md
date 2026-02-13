# Decision Log

|Date|Decision|Rationale|
|---|---|---|
|2026-02-12|Use `hybrid` chatbot retrieval mode by default (KB first, live fallback).|Reduces Atlassian dependency for common queries while preserving graceful degradation when KB misses.|
|2026-02-12|Introduce dedicated `kb_sync` scheduled Lambda for Confluence ingestion.|Keeps request-time chatbot path low-latency and isolates ingestion concerns and permissions.|
|2026-02-12|Normalize Confluence page content to S3 JSON before Bedrock ingestion jobs.|Provides a durable ingest artifact and repeatable, auditable sync input for the configured KB data source.|
