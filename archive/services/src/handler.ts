/**
 * Lambda handler for the TypeScript GitHub App webhook receiver.
 *
 * Responsibilities:
 *  1. Validate the X-Hub-Signature-256 HMAC (raw bytes, before JSON parse)
 *  2. Filter to only supported event/action pairs:
 *       - pull_request: opened / synchronize / reopened / ready_for_review
 *       - issue_comment: created / edited (manual /review trigger)
 *  3. Enqueue a spec-compliant SQS message for the Python worker
 *  4. Return 202 Accepted immediately (GitHub expects fast response)
 *
 * SQS message schema (matches worker/app.py nested path):
 * {
 *   deliveryId: string,
 *   event: string,
 *   action: string,
 *   trigger: "auto" | "manual",
 *   installationId: number,
 *   repo: { owner: string, name: string, fullName: string },
 *   pr: { number: number, headSha: string, baseSha: string },
 *   receivedAt: string  // ISO 8601
 * }
 */

import {
  APIGatewayProxyEventV2,
  APIGatewayProxyResultV2,
  Context,
} from "aws-lambda";
import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";
import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from "@aws-sdk/client-secrets-manager";
import { verifySignature } from "./verifySignature";

const region = process.env.AWS_REGION ?? "us-gov-west-1";
const sqsClient = new SQSClient({ region });
const smClient = new SecretsManagerClient({ region });

/** Module-level cache so we only hit Secrets Manager on cold start. */
let _cachedWebhookSecret: string | null = null;
let _cachedGitHubToken: string | null = null;

async function getWebhookSecret(): Promise<string> {
  if (_cachedWebhookSecret !== null) return _cachedWebhookSecret;
  const secretArn = process.env.WEBHOOK_SECRET_ARN;
  if (!secretArn) throw new Error("WEBHOOK_SECRET_ARN env var not set");
  const response = await smClient.send(
    new GetSecretValueCommand({ SecretId: secretArn })
  );
  const raw = response.SecretString ?? "";
  // Secret may be stored as plain string or JSON object with a key
  try {
    const parsed = JSON.parse(raw) as Record<string, string>;
    _cachedWebhookSecret = parsed.secret ?? parsed.webhook_secret ?? raw;
  } catch {
    _cachedWebhookSecret = raw;
  }
  if (!_cachedWebhookSecret) throw new Error("Webhook secret resolved to empty string");
  return _cachedWebhookSecret;
}

const SUPPORTED_ACTIONS = new Set(["opened", "synchronize", "reopened", "ready_for_review"]);
const TRIGGER_PHRASE = (process.env.REVIEW_TRIGGER_PHRASE ?? "/review").trim();
const BOT_USERNAME = (process.env.BOT_USERNAME ?? "").trim().toLowerCase();

/** Return true if the comment body contains the review trigger phrase. */
function isManualTrigger(body: string): boolean {
  if (!body) return false;
  const lower = body.trim().toLowerCase();
  if (TRIGGER_PHRASE && lower.startsWith(TRIGGER_PHRASE.toLowerCase())) return true;
  if (BOT_USERNAME) {
    if (lower.startsWith(`@${BOT_USERNAME} review`)) return true;
    if (lower.startsWith(`@${BOT_USERNAME} ${TRIGGER_PHRASE.toLowerCase()}`)) return true;
  }
  return false;
}

/** Fetch the current head SHA of a PR via the GitHub API.
 *  Uses the GITHUB_API_BASE env var (defaults to https://api.github.com).
 */
async function fetchPrHeadSha(
  repoFullName: string,
  prNumber: number,
  token: string
): Promise<string | null> {
  const apiBase = (process.env.GITHUB_API_BASE ?? "https://api.github.com").replace(/\/$/, "");
  const url = `${apiBase}/repos/${repoFullName}/pulls/${prNumber}`;
  const resp = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!resp.ok) {
    console.warn("Failed to fetch PR head SHA", { status: resp.status, pr: prNumber });
    return null;
  }
  const data = (await resp.json()) as Record<string, unknown>;
  return ((data.head as Record<string, unknown>)?.sha as string) ?? null;
}

/** Retrieve the GitHub App installation token (simple PAT fallback via env). */
async function getGitHubToken(): Promise<string | null> {
  if (_cachedGitHubToken !== null) return _cachedGitHubToken;
  // Fast path: a plain GitHub token may be injected via env for TS receiver
  const envToken = process.env.GITHUB_TOKEN;
  if (envToken) {
    _cachedGitHubToken = envToken;
    return _cachedGitHubToken;
  }
  return null;
}

/** Retrieve the raw body as a Buffer, handling API GW base64 encoding. */
function getRawBody(event: APIGatewayProxyEventV2): Buffer {
  const body = event.body ?? "";
  if (event.isBase64Encoded) {
    return Buffer.from(body, "base64");
  }
  return Buffer.from(body, "utf8");
}

function respond(statusCode: number, message: string): APIGatewayProxyResultV2 {
  return {
    statusCode,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  };
}

async function enqueueReview(opts: {
  deliveryId: string;
  githubEvent: string;
  action: string;
  trigger: "auto" | "manual";
  installationId: number;
  repoOwner: string;
  repoName: string;
  repoFullName: string;
  prNumber: number;
  headSha: string;
  baseSha: string;
}): Promise<void> {
  const queueUrl = process.env.SQS_QUEUE_URL;
  if (!queueUrl) throw new Error("SQS_QUEUE_URL env var not set");

  const sqsMessage = {
    deliveryId: opts.deliveryId,
    event: opts.githubEvent,
    action: opts.action,
    trigger: opts.trigger,
    installationId: opts.installationId,
    repo: {
      owner: opts.repoOwner,
      name: opts.repoName,
      fullName: opts.repoFullName,
    },
    pr: {
      number: opts.prNumber,
      headSha: opts.headSha,
      baseSha: opts.baseSha,
    },
    receivedAt: new Date().toISOString(),
  };

  await sqsClient.send(
    new SendMessageCommand({
      QueueUrl: queueUrl,
      MessageBody: JSON.stringify(sqsMessage),
    })
  );

  console.info("Enqueued review job", {
    deliveryId: opts.deliveryId,
    trigger: opts.trigger,
    repo: opts.repoFullName,
    pr: opts.prNumber,
    sha: opts.headSha,
  });
}

export async function handler(
  event: APIGatewayProxyEventV2,
  _context: Context
): Promise<APIGatewayProxyResultV2> {
  // ---- 1. Read raw body BEFORE JSON.parse --------------------------------
  const rawBody = getRawBody(event);

  const headers = event.headers ?? {};
  const sigHeader =
    headers["x-hub-signature-256"] ?? headers["X-Hub-Signature-256"] ?? "";
  const deliveryId =
    headers["x-github-delivery"] ?? headers["X-GitHub-Delivery"] ?? "unknown";
  const githubEvent =
    headers["x-github-event"] ?? headers["X-GitHub-Event"] ?? "";

  // ---- 2. Validate signature (constant-time) -----------------------------
  let webhookSecret: string;
  try {
    webhookSecret = await getWebhookSecret();
  } catch (err) {
    console.error("Failed to load webhook secret", { error: err });
    return respond(500, "Server configuration error");
  }

  if (!verifySignature(rawBody, webhookSecret, sigHeader)) {
    console.warn("Signature verification failed", { deliveryId });
    return respond(401, "Invalid signature");
  }

  // ---- 3. Parse body -----------------------------------------------
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawBody.toString("utf8"));
  } catch {
    return respond(400, "Invalid JSON body");
  }

  // ---- 4a. issue_comment path (P1-A manual trigger) ---------------------
  if (githubEvent === "issue_comment") {
    const action = String(payload.action ?? "");
    if (!["created", "edited"].includes(action)) {
      return respond(200, `Ignored issue_comment action: ${action}`);
    }

    const issue = payload.issue as Record<string, unknown> | undefined;
    const comment = payload.comment as Record<string, unknown> | undefined;
    const repository = payload.repository as Record<string, unknown> | undefined;
    const installation = payload.installation as Record<string, unknown> | undefined;

    // Must be a PR comment (issue.pull_request exists)
    if (!issue?.pull_request) {
      return respond(200, "Ignored: comment is not on a pull request");
    }

    const commentBody = String((comment as Record<string, unknown>)?.body ?? "");
    if (!isManualTrigger(commentBody)) {
      return respond(200, "Ignored: comment does not match trigger phrase");
    }

    const repoFullName = String(repository?.full_name ?? "");
    const [repoOwner, repoName] = repoFullName.split("/");
    const prNumber = Number(issue.number);
    const installationId = Number(installation?.id ?? 0);

    if (!prNumber || !repoFullName) {
      return respond(400, "Missing required fields for issue_comment trigger");
    }

    // Fetch current head SHA via GitHub API
    const token = await getGitHubToken();
    if (!token) {
      console.warn("No GitHub token available for manual trigger; cannot fetch head SHA");
      return respond(500, "Server configuration error: no GitHub token for manual trigger");
    }
    const headSha = await fetchPrHeadSha(repoFullName, prNumber, token);
    if (!headSha) {
      return respond(500, "Failed to fetch PR head SHA for manual trigger");
    }

    try {
      await enqueueReview({
        deliveryId,
        githubEvent: "pull_request",
        action: "manual_trigger",
        trigger: "manual",
        installationId,
        repoOwner,
        repoName,
        repoFullName,
        prNumber,
        headSha,
        baseSha: "",
      });
    } catch (err) {
      console.error("Failed to enqueue manual review", { deliveryId, error: err });
      return respond(500, "Failed to enqueue review job");
    }

    return respond(202, "Accepted");
  }

  // ---- 4b. pull_request path (auto trigger) ------------------------------
  if (githubEvent !== "pull_request") {
    return respond(200, `Ignored event: ${githubEvent}`);
  }

  const action = String(payload.action ?? "");
  if (!SUPPORTED_ACTIONS.has(action)) {
    return respond(200, `Ignored action: ${action}`);
  }

  // ---- 5. Extract PR data ------------------------------------------------
  const pr = payload.pull_request as Record<string, unknown> | undefined;
  const repository = payload.repository as Record<string, unknown> | undefined;
  const installation = payload.installation as Record<string, unknown> | undefined;

  if (!pr || !repository) {
    return respond(400, "Missing pull_request or repository in payload");
  }

  const prNumber = pr.number as number;
  const headSha = (pr.head as Record<string, unknown>)?.sha as string;
  const baseSha = (pr.base as Record<string, unknown>)?.sha as string;
  const repoFullName = repository.full_name as string;
  const [repoOwner, repoName] = repoFullName.split("/");
  const installationId = (installation?.id as number | undefined) ?? 0;

  if (!prNumber || !headSha || !repoFullName) {
    return respond(400, "Missing required PR fields");
  }

  // ---- 6. Enqueue SQS message --------------------------------------------
  try {
    await enqueueReview({
      deliveryId,
      githubEvent,
      action,
      trigger: "auto",
      installationId,
      repoOwner,
      repoName,
      repoFullName,
      prNumber,
      headSha,
      baseSha,
    });

    // Fan-out to PR description queue for auto triggers
    const prDescQueueUrl = process.env.PR_DESCRIPTION_QUEUE_URL;
    if (prDescQueueUrl) {
      await sqsClient.send(
        new SendMessageCommand({
          QueueUrl: prDescQueueUrl,
          MessageBody: JSON.stringify({
            deliveryId,
            event: githubEvent,
            action,
            trigger: "auto",
            installationId,
            repo: { owner: repoOwner, name: repoName, fullName: repoFullName },
            pr: { number: prNumber, headSha, baseSha },
            receivedAt: new Date().toISOString(),
          }),
        })
      );
    }
  } catch (err) {
    console.error("Failed to enqueue SQS message", { deliveryId, error: err });
    return respond(500, "Failed to enqueue review job");
  }

  return respond(202, "Accepted");
}


import {
  APIGatewayProxyEventV2,
  APIGatewayProxyResultV2,
  Context,
} from "aws-lambda";
import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";
import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from "@aws-sdk/client-secrets-manager";
import { verifySignature } from "./verifySignature";

const region = process.env.AWS_REGION ?? "us-gov-west-1";
const sqsClient = new SQSClient({ region });
const smClient = new SecretsManagerClient({ region });

/** Module-level cache so we only hit Secrets Manager on cold start. */
let _cachedWebhookSecret: string | null = null;

async function getWebhookSecret(): Promise<string> {
  if (_cachedWebhookSecret !== null) return _cachedWebhookSecret;
  const secretArn = process.env.WEBHOOK_SECRET_ARN;
  if (!secretArn) throw new Error("WEBHOOK_SECRET_ARN env var not set");
  const response = await smClient.send(
    new GetSecretValueCommand({ SecretId: secretArn })
  );
  const raw = response.SecretString ?? "";
  // Secret may be stored as plain string or JSON object with a key
  try {
    const parsed = JSON.parse(raw) as Record<string, string>;
    _cachedWebhookSecret = parsed.secret ?? parsed.webhook_secret ?? raw;
  } catch {
    _cachedWebhookSecret = raw;
  }
  if (!_cachedWebhookSecret) throw new Error("Webhook secret resolved to empty string");
  return _cachedWebhookSecret;
}

const SUPPORTED_ACTIONS = new Set(["opened", "synchronize", "reopened"]);

/** Retrieve the raw body as a Buffer, handling API GW base64 encoding. */
function getRawBody(event: APIGatewayProxyEventV2): Buffer {
  const body = event.body ?? "";
  if (event.isBase64Encoded) {
    return Buffer.from(body, "base64");
  }
  return Buffer.from(body, "utf8");
}

function respond(statusCode: number, message: string): APIGatewayProxyResultV2 {
  return {
    statusCode,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  };
}

export async function handler(
  event: APIGatewayProxyEventV2,
  _context: Context
): Promise<APIGatewayProxyResultV2> {
  // ---- 1. Read raw body BEFORE JSON.parse --------------------------------
  const rawBody = getRawBody(event);

  const headers = event.headers ?? {};
  const sigHeader =
    headers["x-hub-signature-256"] ?? headers["X-Hub-Signature-256"] ?? "";
  const deliveryId =
    headers["x-github-delivery"] ?? headers["X-GitHub-Delivery"] ?? "unknown";
  const githubEvent =
    headers["x-github-event"] ?? headers["X-GitHub-Event"] ?? "";

  // ---- 2. Validate signature (constant-time) -----------------------------
  let webhookSecret: string;
  try {
    webhookSecret = await getWebhookSecret();
  } catch (err) {
    console.error("Failed to load webhook secret", { error: err });
    return respond(500, "Server configuration error");
  }

  if (!verifySignature(rawBody, webhookSecret, sigHeader)) {
    console.warn("Signature verification failed", { deliveryId });
    return respond(401, "Invalid signature");
  }

  // ---- 3. Parse and filter -----------------------------------------------
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(rawBody.toString("utf8"));
  } catch {
    return respond(400, "Invalid JSON body");
  }

  if (githubEvent !== "pull_request") {
    return respond(200, `Ignored event: ${githubEvent}`);
  }

  const action = String(payload.action ?? "");
  if (!SUPPORTED_ACTIONS.has(action)) {
    return respond(200, `Ignored action: ${action}`);
  }

  // ---- 4. Extract PR data ------------------------------------------------
  const pr = payload.pull_request as Record<string, unknown> | undefined;
  const repository = payload.repository as Record<string, unknown> | undefined;
  const installation = payload.installation as Record<string, unknown> | undefined;

  if (!pr || !repository) {
    return respond(400, "Missing pull_request or repository in payload");
  }

  const prNumber = pr.number as number;
  const headSha = (pr.head as Record<string, unknown>)?.sha as string;
  const baseSha = (pr.base as Record<string, unknown>)?.sha as string;
  const repoFullName = repository.full_name as string;
  const [repoOwner, repoName] = repoFullName.split("/");
  const installationId = (installation?.id as number | undefined) ?? 0;

  if (!prNumber || !headSha || !repoFullName) {
    return respond(400, "Missing required PR fields");
  }

  // ---- 5. Enqueue SQS message --------------------------------------------
  const sqsMessage = {
    deliveryId,
    event: githubEvent,
    action,
    installationId,
    repo: {
      owner: repoOwner,
      name: repoName,
      fullName: repoFullName,
    },
    pr: {
      number: prNumber,
      headSha,
      baseSha,
    },
    receivedAt: new Date().toISOString(),
  };

  const queueUrl = process.env.SQS_QUEUE_URL;
  if (!queueUrl) {
    console.error("SQS_QUEUE_URL env var not set");
    return respond(500, "Server configuration error");
  }

  try {
    await sqsClient.send(
      new SendMessageCommand({
        QueueUrl: queueUrl,
        MessageBody: JSON.stringify(sqsMessage),
      })
    );
  } catch (err) {
    console.error("Failed to enqueue SQS message", { deliveryId, error: err });
    return respond(500, "Failed to enqueue review job");
  }

  console.info("Enqueued review job", {
    deliveryId,
    repo: repoFullName,
    pr: prNumber,
    sha: headSha,
  });

  return respond(202, "Accepted");
}
