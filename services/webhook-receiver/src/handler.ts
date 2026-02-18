/**
 * Lambda handler for the TypeScript GitHub App webhook receiver.
 *
 * Responsibilities:
 *  1. Validate the X-Hub-Signature-256 HMAC (raw bytes, before JSON parse)
 *  2. Filter to only supported event/action pairs (pull_request opened/synchronize/reopened)
 *  3. Enqueue a spec-compliant SQS message for the Python worker
 *  4. Return 202 Accepted immediately (GitHub expects fast response)
 *
 * SQS message schema (matches worker/app.py nested path):
 * {
 *   deliveryId: string,
 *   event: string,
 *   action: string,
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
