from unittest.mock import patch

from shared.github_app_auth import GitHubAppAuth


TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDICR37WOX17rBb
meYfD6mD6A0R2Y3wIi1a9UfI7DZPP4P+f57J+a5q7fN7ncfwJquV77YJ5f4HV17I
BUmkeR3+4W5a1qMws2DKrR9eLusupQ5U3xJ4su4nTA7MlR6wTUn1HSfggPLQpYn8
ggSN2f77xuYpiGsQz6+2hL3xT84hAgyV4yIAJ4eMswqjBr7fIs0i7f9KebS6fQ8S
bfuQks8J0j4hLQm4wWwEM6q6dfIP5B5NMuZ6GM8Y3hXqlSz6ltWWzVwXf3J8mLYu
KwQ47lxzB6yhaVgM8n1LsWKyq0IuKgE8KIO0UwDSmOpWq4P5cmg8R5rUV6j4XhSY
2aM7Rr2nAgMBAAECggEAH4M8qFy+bS5Nn2+7bN9MS/vTZBvG62DIFBrWDy0n9ypE
fE90n5AMH9OuTrWaQ2wVSHZ2P+2QhPe9xPg3R2J8u8mTgBsBbJwff7+F+0Q8i0h8
z1wfovZ9ZYB5lrwXj3P30Jxy6S46icW1+3lJS+8zh1ULJ1rV9P4zQSr4xg6epRPW
q4jsXjzBOMh8wFGoxd7eV7ptYE11MWxmG7OBG4CVWj6ItzX3vJ8iBfplFdfI+7pw
3q7j+S3pY2hAtx9lQ1te2NfgNmfU3f5iX4VLXQ8jPxYQ2DQLgQkgOXxAMas7QcMq
L9X7q8m7fJ6M8y5WvOOw2jz8g8qQzY5Kx7Q90vmKQQKBgQDo4MsT4h2k95uDai1Z
lI6mqhxb2cEqdmQ8gfo48h3jo9iTWp6+X2JYgJ6Eh57J62DeW8Lxkh8ho8xJPSpG
A7V9Ek4CxQVGtEwA8PJuM6jDgNN7S8s2AjJ1qzVhQ+Lj6uQfM6cL7y2R8FG5v6m7
Ix2Rkq8BQhI2RTzmn1YMRcR96QKBgQDdOj9qI5mnu3Z0mtR3SR8FJj5x6Q+g6fM4
nOh4Q6kVfOt0gNf1y5hA3xe1W6D2nSaKSMn2HR6f8wA6N1pVwDFVe+5F9xIqW/Vx
8J8jT8x+NG8g3TNTkW8u4KlfR+w2cvd3y8V7rGYhW4MM9xB5LI3hYk8CjMD2vU5Y
2vQ2v9cWlQKBgQC13hHcN2S3J9ffz8s2h7j6CvbzI0Qk3zY3jXAU4hJsnDKB8N0A
mTxm3Z2QqQ6bW6J8Sx8qAb6QJ0ti1YyN4lNtEEf3yq9A9sLk5P79tK9S3dA6VwCe
jdrq6v4qR2xI1p6O0gN4Rj5Hk9me2EtSN7EziBpfzKplOE1v8R1M2cn5gQKBgB1g
Q8Cw5RzjVhQ2d9+QjVZ3aw83b3Xc5d0TUE9IXq7W0X8Vey4pmt8kJpAC9P4gV4R7
jCjLS2f5nSev53v1c9a3dYfSM0qW6HLKtP6pLkQk9IpX9kqC1l4Pz2VhfF9P1Z2L
f3PfQb9IhbzS3xsnR1d0vYqZ9J9wkl8FNTngwQWJAoGAb2pvN8m9Z2zA6J2tWW8M
D+nvtM3TRXvdrg7hL2WnFYh4c6nP1E+9nI9VqOjxQ9Q4Y2lLQ+fH0h4PQV2USGm+
6yutvJJvQ1dML6Xg6OCgvQ2fyA4S4ztSfrlF3fTxX9CzALgMchx58Y6JSiXrKqXy
YxqWjGd++I2t7Po9s7+99A8=
-----END PRIVATE KEY-----"""


class FakeSecretsClient:
    def get_secret_value(self, SecretId: str) -> dict:
        if SecretId == "ids":
            return {"SecretString": '{"app_id":"12345","installation_id":"98765"}'}
        if SecretId == "pem":
            return {"SecretString": TEST_PRIVATE_KEY}
        raise ValueError("unexpected secret")


def test_create_app_jwt_contains_issuer() -> None:
    auth = GitHubAppAuth(
        app_ids_secret_arn="ids",
        private_key_secret_arn="pem",
        secrets_client=FakeSecretsClient(),
    )

    with patch("shared.github_app_auth.jwt.encode", return_value="signed-token") as encode_mock:
        token = auth.create_app_jwt()

    assert token == "signed-token"
    args, kwargs = encode_mock.call_args
    claims = args[0]
    assert claims["iss"] == "12345"
    assert "iat" in claims
    assert "exp" in claims
    assert kwargs["algorithm"] == "RS256"
