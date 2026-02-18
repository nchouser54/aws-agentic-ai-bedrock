/**
 * HMAC SHA-256 webhook signature verification for GitHub App webhooks.
 *
 * IMPORTANT: This function must receive the RAW request body bytes BEFORE
 * any JSON parsing, because JSON parsing can alter whitespace/ordering and
 * will break the HMAC digest verification.
 *
 * GitHub sends the signature in the header:
 *   X-Hub-Signature-256: sha256=<hex>
 *
 * See: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
 */

import { createHmac, timingSafeEqual } from "crypto";

/**
 * Verify the GitHub webhook signature against the raw body.
 *
 * @param rawBody   - Raw request body as a Buffer or UTF-8 string
 * @param secret    - Webhook secret stored in Secrets Manager
 * @param signature - Value of ``X-Hub-Signature-256`` header (e.g. "sha256=abc123")
 * @returns true if the signature is valid, false otherwise
 */
export function verifySignature(
  rawBody: Buffer | string,
  secret: string,
  signature: string
): boolean {
  if (!signature || !signature.startsWith("sha256=")) {
    return false;
  }

  const body = typeof rawBody === "string" ? Buffer.from(rawBody, "utf8") : rawBody;
  const expected = signature.slice("sha256=".length);

  const hmac = createHmac("sha256", secret);
  hmac.update(body);
  const digest = hmac.digest("hex");

  // timingSafeEqual requires equal-length Buffers to prevent timing attacks
  const digestBuf = Buffer.from(digest, "hex");
  const expectedBuf = Buffer.from(expected, "hex");

  if (digestBuf.length !== expectedBuf.length) {
    return false;
  }

  return timingSafeEqual(digestBuf, expectedBuf);
}
