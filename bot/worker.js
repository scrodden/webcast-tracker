// WebcastTrackerBot — identity for the webcast-tracker crawler.
//
// Deploy as a Cloudflare Worker (see bot/README.md). It serves:
//   /.well-known/http-message-signatures-directory  the bot's public key, as a
//       signed JSON Web Key Set (Web Bot Auth key directory, which Cloudflare's
//       Verified Bots program checks)
//   /   a page explaining what the bot does and how to reach its operator
//
// Settings (Worker → Settings → Variables and Secrets):
//   SIGNING_KEY  (secret)  private key printed by `python -m irwebcasts botkey`
//   PUBLIC_KEY   (text)    public key printed by the same command
//   CONTACT      (text)    an email address site owners can write to
//   SITE         (text)    the public website, e.g. https://scrodden.github.io/webcast-tracker/

const DIRECTORY_PATH = "/.well-known/http-message-signatures-directory";

function b64urlToBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}
function bytesToB64(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}
function bytesToB64url(bytes) {
  return bytesToB64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// RFC 7638 JWK thumbprint, used as the key id.
async function thumbprint(x) {
  const canonical = JSON.stringify({ crv: "Ed25519", kty: "OKP", x });
  return bytesToB64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical)));
}

export async function directoryResponse(request, env, now = Math.floor(Date.now() / 1000)) {
  const x = env.PUBLIC_KEY.trim();
  const key = await crypto.subtle.importKey(
    "jwk", { kty: "OKP", crv: "Ed25519", x, d: env.SIGNING_KEY.trim() }, { name: "Ed25519" }, false, ["sign"]);
  const keyid = await thumbprint(x);
  const nonce = bytesToB64(crypto.getRandomValues(new Uint8Array(64)));
  const authority = new URL(request.url).host.toLowerCase();
  const params = `("@authority";req);alg="ed25519";keyid="${keyid}";nonce="${nonce}";` +
    `tag="http-message-signatures-directory";created=${now};expires=${now + 300}`;
  const base = `"@authority";req: ${authority}\n"@signature-params": ${params}`;
  const signature = bytesToB64(await crypto.subtle.sign("Ed25519", key, new TextEncoder().encode(base)));
  return new Response(JSON.stringify({ keys: [{ kty: "OKP", crv: "Ed25519", x }] }), {
    headers: {
      "Content-Type": "application/http-message-signatures-directory+json",
      "Signature": `sig1=:${signature}:`,
      "Signature-Input": `sig1=${params}`,
      "Cache-Control": "max-age=86400",
    },
  });
}

function infoPage(env) {
  const contact = env.CONTACT ? `<a href="mailto:${env.CONTACT}">${env.CONTACT}</a>` : "the address on the website";
  const site = env.SITE || "https://scrodden.github.io/webcast-tracker/";
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>WebcastTrackerBot</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#1d1d1f}
code{background:#f0f0ec;padding:1px 5px;border-radius:4px}</style></head><body>
<h1>WebcastTrackerBot</h1>
<p>WebcastTrackerBot collects links to the <b>public webcasts</b> of listed companies — earnings
calls, investor conferences, investor days and shareholder meetings — from their investor-relations
pages and press releases, and lists them on <a href="${site}">${site}</a> so investors can find them.</p>
<h2>How it behaves</h2>
<ul>
<li>Identifies itself as <code>WebcastTrackerBot</code> in its user agent and signs every request
(Web Bot Auth; public key at <a href="${DIRECTORY_PATH}"><code>${DIRECTORY_PATH}</code></a>).</li>
<li>Follows <code>robots.txt</code>. To keep it out of a site, add
<code>User-agent: WebcastTrackerBot</code> / <code>Disallow: /</code>.</li>
<li>Reads only public investor-relations pages, events pages and press releases; never logs in,
registers, submits forms or plays media.</li>
<li>Loads at most one page per second from a site, and visits each company about once a day.</li>
<li>Stores only the event title, date and webcast link — not page content.</li>
</ul>
<h2>Contact</h2>
<p>Questions or requests: ${contact}.</p>
</body></html>`, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === DIRECTORY_PATH) return directoryResponse(request, env);
    if (path === "/" || path === "") return infoPage(env);
    return new Response("Not found", { status: 404 });
  },
};
