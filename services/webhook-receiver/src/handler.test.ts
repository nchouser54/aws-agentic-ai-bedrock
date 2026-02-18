import { verifySignature } from "./verifySignature";
import { handler } from "./handler";
import { SQSClient } from "@aws-sdk/client-sqs";
import { createHmac } from "crypto";
import type { APIGatewayProxyEventV2, Context } from "aws-lambda";

// ---- verifySignature tests -----------------------------------------------

describe("verifySignature", () => {
  const secret = "test-webhook-secret";
  const body = Buffer.from('{"action":"opened"}', "utf8");

  function makeSignature(b: Buffer, s: string): string {
    return "sha256=" + createHmac("sha256", s).update(b).digest("hex");
  }

  it("returns true for a valid signature", () => {
    const sig = makeSignature(body, secret);
    expect(verifySignature(body, secret, sig)).toBe(true);
  });

  it("returns false for a tampered body", () => {
    const sig = makeSignature(body, secret);
    const tampered = Buffer.from('{"action":"closed"}', "utf8");
    expect(verifySignature(tampered, secret, sig)).toBe(false);
  });

  it("returns false for a wrong secret", () => {
    const sig = makeSignature(body, "wrong-secret");
    expect(verifySignature(body, secret, sig)).toBe(false);
  });

  it("returns false when signature header is missing", () => {
    expect(verifySignature(body, secret, "")).toBe(false);
  });

  it("returns false when signature lacks sha256= prefix", () => {
    expect(verifySignature(body, secret, "abcdef")).toBe(false);
  });

  it("accepts a string body the same as Buffer", () => {
    const strBody = '{"action":"opened"}';
    const sig = makeSignature(Buffer.from(strBody, "utf8"), secret);
    expect(verifySignature(strBody, secret, sig)).toBe(true);
  });
});

// ---- handler tests -------------------------------------------------------

// Mock SQS
jest.mock("@aws-sdk/client-sqs", () => {
  const sendMock = jest.fn().mockResolvedValue({});
  return {
    SQSClient: jest.fn().mockImplementation(() => ({ send: sendMock })),
    SendMessageCommand: jest.fn().mockImplementation((input) => input),
    __sendMock: sendMock,
  };
});

// Mock Secrets Manager — returns the secret set in process.env._TEST_WEBHOOK_SECRET
jest.mock("@aws-sdk/client-secrets-manager", () => {
  const sendMock = jest.fn().mockImplementation(() =>
    Promise.resolve({ SecretString: process.env._TEST_WEBHOOK_SECRET ?? "" })
  );
  return {
    SecretsManagerClient: jest.fn().mockImplementation(() => ({ send: sendMock })),
    GetSecretValueCommand: jest.fn().mockImplementation((input) => input),
  };
});

const { __sendMock } = jest.requireMock("@aws-sdk/client-sqs") as {
  __sendMock: jest.Mock;
};

function buildBody(action = "opened") {
  return JSON.stringify({
    action,
    installation: { id: 12345 },
    pull_request: {
      number: 42,
      head: { sha: "abc1234" },
      base: { sha: "def5678" },
    },
    repository: {
      full_name: "acme/my-repo",
    },
  });
}

function makeEvent(
  bodyStr: string,
  secret: string,
  githubEvent = "pull_request",
  base64 = false
): APIGatewayProxyEventV2 {
  const bodyBuf = Buffer.from(bodyStr, "utf8");
  const sig =
    "sha256=" + createHmac("sha256", secret).update(bodyBuf).digest("hex");

  return {
    version: "2.0",
    routeKey: "POST /webhook",
    rawPath: "/webhook",
    rawQueryString: "",
    headers: {
      "x-hub-signature-256": sig,
      "x-github-delivery": "delivery-001",
      "x-github-event": githubEvent,
    },
    requestContext: {} as never,
    body: base64 ? bodyBuf.toString("base64") : bodyStr,
    isBase64Encoded: base64,
  };
}

const SECRET = "handler-test-secret";
const fakeContext = {} as Context;

beforeEach(() => {
  // Reset module-level secret cache so each test gets a fresh fetch
  jest.resetModules();
  process.env._TEST_WEBHOOK_SECRET = SECRET;
  process.env.WEBHOOK_SECRET_ARN = "arn:aws:secretsmanager:us-gov-west-1:123456789012:secret:webhook-secret";
  process.env.SQS_QUEUE_URL = "https://sqs.us-gov-west-1.amazonaws.com/123/review";
  __sendMock.mockClear();
});

describe("handler", () => {
  it("returns 202 and enqueues for a valid opened event", async () => {
    const event = makeEvent(buildBody("opened"), SECRET);
    const result = await handler(event, fakeContext);
    expect((result as { statusCode: number }).statusCode).toBe(202);
    expect(__sendMock).toHaveBeenCalledTimes(1);
  });

  it("returns 401 for invalid signature", async () => {
    const event = makeEvent(buildBody(), "wrong-secret");
    const result = await handler(event, fakeContext);
    expect((result as { statusCode: number }).statusCode).toBe(401);
    expect(__sendMock).not.toHaveBeenCalled();
  });

  it("returns 200 and ignores non-pull_request events", async () => {
    const event = makeEvent(buildBody(), SECRET, "push");
    const result = await handler(event, fakeContext);
    expect((result as { statusCode: number }).statusCode).toBe(200);
    expect(__sendMock).not.toHaveBeenCalled();
  });

  it("returns 200 and ignores unsupported actions", async () => {
    const event = makeEvent(buildBody("closed"), SECRET);
    const result = await handler(event, fakeContext);
    expect((result as { statusCode: number }).statusCode).toBe(200);
    expect(__sendMock).not.toHaveBeenCalled();
  });

  it("handles base64-encoded body correctly", async () => {
    const event = makeEvent(buildBody("synchronize"), SECRET, "pull_request", true);
    const result = await handler(event, fakeContext);
    expect((result as { statusCode: number }).statusCode).toBe(202);
  });

  it("enqueues a spec-compliant SQS message", async () => {
    const event = makeEvent(buildBody("opened"), SECRET);
    await handler(event, fakeContext);
    const call = __sendMock.mock.calls[0][0] as Record<string, unknown>;
    const msgBody = JSON.parse(call.MessageBody as string);
    expect(msgBody.repo.owner).toBe("acme");
    expect(msgBody.repo.name).toBe("my-repo");
    expect(msgBody.repo.fullName).toBe("acme/my-repo");
    expect(msgBody.pr.number).toBe(42);
    expect(msgBody.pr.headSha).toBe("abc1234");
    expect(msgBody.pr.baseSha).toBe("def5678");
    expect(msgBody.installationId).toBe(12345);
    expect(msgBody.deliveryId).toBe("delivery-001");
  });
});
