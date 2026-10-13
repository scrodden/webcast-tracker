# Registering WebcastTrackerBot with Cloudflare

Many company IR sites sit behind Cloudflare, which turns away unidentified bots.
Cloudflare lets through bots in its **Verified Bots** program. To qualify, a bot must
(1) prove who it is by signing every request ("Web Bot Auth") and (2) behave well
(obey robots.txt, keep request rates low). The crawler already does both; these
steps publish its public key and register it.

You'll need: a free Cloudflare account, and the two keys from
`python -m irwebcasts botkey` (SIGNING_KEY is secret; PUBLIC_KEY is not).

## 1. Create the Worker (serves the public key and an "about this bot" page)

1. Sign in at https://dash.cloudflare.com (create a free account if needed).
2. **Workers & Pages → Create → Create Worker** (start from "Hello World").
3. Name it `webcast-tracker-bot` and click **Deploy**.
4. Click **Edit code**, delete everything, paste the contents of `bot/worker.js`, click **Deploy**.
5. Note its address, shown at the top: `https://webcast-tracker-bot.<your-name>.workers.dev`.
6. **Settings → Variables and Secrets → Add**:

   | Type   | Name          | Value |
   |--------|---------------|-------|
   | Secret | `SIGNING_KEY` | the SIGNING_KEY from `botkey` |
   | Text   | `PUBLIC_KEY`  | the PUBLIC_KEY from `botkey` |
   | Text   | `CONTACT`     | an email address site owners can write to |
   | Text   | `SITE`        | `https://scrodden.github.io/webcast-tracker/` |

   Click **Deploy**.
7. Check: opening the Worker address shows the "WebcastTrackerBot" page, and
   `…workers.dev/.well-known/http-message-signatures-directory` shows `{"keys":[…]}`.

## 2. Turn on signing in GitHub

In the repository: **Settings → Secrets and variables → Actions**

- **Secrets** tab → New repository secret: `IRW_SIGNING_KEY` = the same SIGNING_KEY
- **Variables** tab → New repository variable: `IRW_KEY_DIRECTORY` = the Worker address
  (`https://webcast-tracker-bot.<your-name>.workers.dev`)

From the next daily run, every request carries the signature and the user agent
`WebcastTrackerBot/1.0` with a link to the Worker's page.

## 3. Submit the bot to Cloudflare

Open the BotBase submission form:
https://dash.cloudflare.com/?to=/:account/application-security/botbase/form

| Field | Answer |
|---|---|
| Bot name | WebcastTrackerBot |
| Operator / website | https://scrodden.github.io/webcast-tracker/ |
| Purpose / category | Aggregator (collects links to public investor webcasts) |
| Description | Collects links to the public webcasts of listed companies (earnings calls, investor conferences, investor days, shareholder meetings) from their investor-relations pages and press releases, and lists them on a free public website. Reads only public IR pages, follows robots.txt, loads at most one page per second per site, visits each company about once a day, and stores only event titles, dates and links. |
| Verification method | Request Signature (Web Bot Auth) |
| Validation instructions / key directory | `https://webcast-tracker-bot.<your-name>.workers.dev/.well-known/http-message-signatures-directory` |
| User agent | `WebcastTrackerBot` (pattern: contains `WebcastTrackerBot`) |
| Info / documentation URL | `https://webcast-tracker-bot.<your-name>.workers.dev/` |
| Contact | your email |

Track it under **BotBase → Submission history** (Waiting For Review → Accepted / Rejected).
A rejection doesn't show a reason; Cloudflare Support can tell you why.

## Checking it works

Cloudflare's test endpoint reports how it sees a signed request:
`https://crawltest.com/cdn-cgi/web-bot-auth` answers **401** while the key is unknown
(signature well-formed) and **200** once it is registered and verified.

## Notes

- Verification gets the crawler past Cloudflare's general bot blocking. Individual
  companies can still choose to block verified bots, so some sites may stay closed.
- Akamai (used by e.g. Lilly) and other providers have their own programs.
- If the private key ever leaks, run `botkey` again, update the Worker and GitHub
  secrets, and tell Cloudflare about the new key.
