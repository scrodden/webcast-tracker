"""Web Bot Auth: sign every request so sites can verify who the crawler is.

Implements the scheme Cloudflare uses for Verified Bots
(https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/):
each request carries

  Signature-Agent: "https://<key directory host>"
  Signature-Input: sig1=("@authority" "signature-agent");created=…;keyid="<JWK thumbprint>";
                   alg="ed25519";expires=…;nonce="…";tag="web-bot-auth"
  Signature:       sig1=:<Ed25519 signature, base64>:

The key is an Ed25519 private key given as IRW_SIGNING_KEY (base64url of the raw
32-byte key, as printed by `python -m irwebcasts botkey`). IRW_KEY_DIRECTORY is the
https origin that serves the public key (the Cloudflare Worker in bot/worker.js).
Without both, requests go out unsigned.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlsplit

TAG = "web-bot-auth"
VALIDITY_SECONDS = 60


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _private_key(raw):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(b64url_decode(raw.strip()))


def public_jwk(private_key):
    from cryptography.hazmat.primitives import serialization
    x = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": b64url(x)}


def thumbprint(jwk):
    """RFC 7638 JWK thumbprint (SHA-256, base64url)."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]},
                           separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(canonical.encode()).digest())


def generate():
    """New key: (private key for the secrets, public JWK, thumbprint)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    jwk = public_jwk(key)
    return b64url(raw), jwk, thumbprint(jwk)


def authority(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    default = {"https": 443, "http": 80}.get(parts.scheme)
    return host if parts.port in (None, default) else f"{host}:{parts.port}"


class Signer:
    def __init__(self, private_key_b64, directory):
        self.key = _private_key(private_key_b64)
        self.keyid = thumbprint(public_jwk(self.key))
        self.agent = f'"{directory.rstrip("/")}"'

    def headers(self, url, now=None, nonce=None):
        """The three Web Bot Auth headers for a request to `url`."""
        created = int(now if now is not None else time.time())
        nonce = nonce or base64.b64encode(secrets.token_bytes(64)).decode()  # the spec requires 64 bytes
        params = (f'("@authority" "signature-agent");created={created};keyid="{self.keyid}";'
                  f'alg="ed25519";expires={created + VALIDITY_SECONDS};nonce="{nonce}";tag="{TAG}"')
        base = (f'"@authority": {authority(url)}\n'
                f'"signature-agent": {self.agent}\n'
                f'"@signature-params": {params}')
        signature = base64.b64encode(self.key.sign(base.encode())).decode()
        return {
            "Signature-Agent": self.agent,
            "Signature-Input": f"sig1={params}",
            "Signature": f"sig1=:{signature}:",
        }


def from_env():
    key, directory = os.environ.get("IRW_SIGNING_KEY"), os.environ.get("IRW_KEY_DIRECTORY")
    if not key or not directory:
        return None
    if not directory.startswith("https://"):
        raise SystemExit("IRW_KEY_DIRECTORY must be an https:// address")
    return Signer(key, directory)


def requests_auth(signer):
    """A requests auth hook that signs each outgoing request (including redirects)."""
    import requests

    class _Auth(requests.auth.AuthBase):
        def __call__(self, request):
            request.headers.update(signer.headers(request.url))
            return request
    return _Auth()
