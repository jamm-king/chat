# Notion OAuth: Backend Integration Contract

Updated: 2026-11-02. Implementation: `ai/app`.

This document describes the three implemented AI endpoints used to connect a
Notion workspace to an authenticated Chat user. Backend authentication, cookie
relay, and completion UI are integration work; they are not implemented by these
AI endpoints. The separate [RAG proposal](references.md) is not this contract.

## Ownership and prerequisites

| Component | Responsibility |
| --- | --- |
| Backend | Authenticate the Chat session; derive `userId`; call AI using the service token; relay the OAuth cookie and callback. |
| AI | Generate and validate OAuth state; exchange the authorization code; encrypt and persist Notion credentials. |
| Notion | Authenticate the Notion user, obtain page-sharing consent, and issue the code and credentials. |
| Browser | Store the OAuth cookie and navigate through the Notion authorization flow. |

Register a public Notion connection with an OAuth client ID, client secret, and
redirect URI. The redirect URI registered with Notion must match AI's
`NOTION_REDIRECT_URI`. The configured path must be
`/integrations/notion/callback`; HTTPS is required except for supported localhost
addresses. See the [official Notion authorization guide](https://developers.notion.com/guides/get-started/authorization).

Do not expose `AI_SERVICE_TOKEN`, the Notion client secret, the encryption key,
or Notion tokens to frontend code. `AI_SERVICE_TOKEN` authenticates Backend to
AI; it is not a Notion access token. AI trusts Backend's `userId`; it does not
authenticate Chat login sessions.

## Addresses and common conventions

Example local topology:

| Purpose | Address |
| --- | --- |
| AI internal base URL | `http://localhost:8001` |
| Backend browser-facing origin | `http://localhost:8000` |
| Browser-facing callback through Backend | `http://localhost:8000/integrations/notion/callback` |

Backend must implement the browser-facing routes and relay described below.
For an AI-only browser test, use
`http://localhost:8001/integrations/notion/callback` instead.

Requests and responses use JSON where applicable. IDs are UUIDs and timestamp
fields are ISO 8601 date-time strings. Query names are case-sensitive:
`userId` is camelCase; response fields are snake_case. Every successful endpoint
below returns `Cache-Control: no-store`.

## 1. Start authorization

```http
GET /integrations/notion/authorize?userId=11111111-1111-4111-8111-111111111111
Authorization: Bearer <AI_SERVICE_TOKEN>
```

| Input | Location | Required | Rule |
| --- | --- | --- | --- |
| Service token | Authorization header | Yes | Configured `AI_SERVICE_TOKEN`. |
| `userId` | Query | Yes | User UUID derived from Backend's authenticated session. |

Success: `200 OK`.

```json
{
  "authorization_url": "https://api.notion.com/v1/oauth/authorize?client_id=CLIENT_ID&redirect_uri=ENCODED_REDIRECT_URI&response_type=code&owner=user&state=OPAQUE_STATE"
}
```

The URL above is illustrative; navigate to the exact returned URL. This endpoint
returns JSON, not an HTTP redirect. It also returns a browser-binding cookie:

```http
Set-Cookie: notion_oauth_browser=OPAQUE_BROWSER_TOKEN; HttpOnly; Max-Age=600; Path=/integrations/notion/callback; SameSite=lax
```

- No `Domain` is set. The browser stores a host-only cookie for the host serving
  the browser-facing response.
- `Max-Age` follows `OAUTH_STATE_TTL_SECONDS`, default 600 seconds.
- `Secure` is added when `OAUTH_COOKIE_SECURE=true` or the redirect URI uses HTTPS.
- AI stores `state -> user_id, browser_token, expiry` in process memory. The
  authorization URL does not contain the Chat user ID.
- Restarting AI invalidates pending authorizations. Use one AI process for this
  flow; separate worker processes do not share pending state.

## 2. Complete authorization

After consent, Notion redirects the browser to the registered redirect URI.
Backend must relay the following request to AI when Backend owns that URI:

```http
GET /integrations/notion/callback?state=OPAQUE_STATE&code=AUTHORIZATION_CODE
Cookie: notion_oauth_browser=OPAQUE_BROWSER_TOKEN
```

| Input | Location | Required | Rule |
| --- | --- | --- | --- |
| `state` | Query | Yes | 1-256 characters; must match pending state. |
| `code` | Query | On consent | Maximum 4,096 characters. |
| `error` | Query | On cancellation | Maximum 256 characters; relay if provided by Notion. |
| `notion_oauth_browser` | Cookie | Yes | Must match the browser token stored with state. |

No service bearer token or `userId` is required on this endpoint. State restores
the user ID; the cookie binds completion to the initiating browser. Do not replace
this with a user ID supplied by the browser.

AI validates state, expiry, and the browser cookie, then consumes the valid state
before processing cancellation or exchanging the code. Successful state validation
is single-use, including when later token exchange or storage fails. Start a new
authorization after such a failure. An unknown, expired, or mismatched state never
triggers a token exchange.

AI exchanges the code server-to-server with
`POST https://api.notion.com/v1/oauth/token`, using HTTP Basic authentication with
the configured client ID and secret, and this JSON body:

```json
{
  "grant_type": "authorization_code",
  "code": "AUTHORIZATION_CODE",
  "redirect_uri": "http://localhost:8000/integrations/notion/callback"
}
```

AI encrypts the access token and any returned refresh token using Fernet and
saves them in its `notion_connections` table. Connections are unique by
`(user_id, workspace_id, bot_id)`. Reauthorization updates the credentials of an
existing matching connection; a user can have multiple connections. The user ID
comes from pending state, not the Notion token response. Keep the encryption key
stable across restarts. Automatic token refresh is not implemented.

Success: `200 OK`, with the connection object below. Tokens are never returned.

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "workspace_id": "33333333-3333-4333-8333-333333333333",
  "workspace_name": "Example workspace",
  "bot_id": "44444444-4444-4444-8444-444444444444",
  "created_at": "2026-11-02T01:00:00Z",
  "status": "connected"
}
```

`workspace_name` may be null. `id` is the AI connection ID, not a user or workspace
ID. `created_at` is the connection's original creation time. `status` is a static
response value, not a live token-validity check.

Handled callback responses include `Referrer-Policy: no-referrer` and a
`Set-Cookie` header that deletes the OAuth cookie at the same path. Relay the
deletion header on success and handled failure. FastAPI validation failures can
occur before this handler runs and do not perform this cleanup.

The current AI callback returns JSON. It does not redirect to the frontend or
notify Backend separately. Backend must implement any completion redirect/UI.

## 3. List saved connections

```http
GET /integrations/notion/connections?userId=11111111-1111-4111-8111-111111111111
Authorization: Bearer <AI_SERVICE_TOKEN>
```

Required inputs are the same as authorization start. Success is `200 OK` with an
array of the connection objects above, or `[]` if none exist. There is no
pagination or guaranteed ordering. This reads saved connections without calling
Notion. Backend can use it to reconcile connection state after browser completion.

## Backend cookie relay

```text
Browser -> Backend: Start connection using the Chat login session
Backend -> AI: GET /authorize?userId=... with service bearer token
AI -> Backend: authorization_url + Set-Cookie
Backend -> Browser: authorization_url + each Set-Cookie header
Browser -> Notion: Navigate to authorization_url and grant access
Notion -> Browser: Redirect to the registered callback with code + state
Browser -> Backend callback: code + state + OAuth Cookie
Backend -> AI callback: code + state + OAuth Cookie
AI -> Notion: Exchange code for credentials
AI -> AI database: Save encrypted credentials linked to user_id
AI -> Backend -> Browser: Connection result + cookie deletion header
```

Backend must forward each `Set-Cookie` as a separate response header; do not
comma-join them. For an HTTPX response and a FastAPI/Starlette browser response,
the header-copying portion is:

```python
for cookie in upstream.headers.get_list("set-cookie"):
    response.headers.append("set-cookie", cookie)
```

On callback, forward `state` and whichever of `code` and `error` are present.
Forward only the `notion_oauth_browser` cookie to AI, not the Chat login cookie
or unrelated browser cookies. Use the current browser request's cookie, not a
shared Backend HTTP client's cookie jar across users.

Keep the browser-facing callback on the same host that set the cookie and use
`/integrations/notion/callback` so the current cookie path matches. Do not mix
`localhost` and `127.0.0.1`. Cookies are not isolated by port; different hosts or
subdomains still need an explicit routing/cookie design. Forwarding a host-only
cookie set on a Backend host does not make it available to a different AI host.

If frontend JavaScript calls Backend across origins, include credentials and
configure Backend CORS with the explicit frontend origin and credentials enabled.
Frontend JavaScript cannot read `Set-Cookie`; the browser handles it. SameSite and
browser cookie policy still apply to cross-site deployments. See
[MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).

## Errors

These endpoints currently use FastAPI's `detail` error format, not the proposed
RAG `error.code` envelope. Do not rely on a normalized provider-specific error
code for OAuth exchange failures.

| Endpoint | HTTP | Meaning |
| --- | --- | --- |
| Start / list | 401 | Missing or incorrect service token; `WWW-Authenticate: Bearer`. |
| Any | 422 | Missing or invalid required query input. |
| Callback | 400 | Unknown, expired, reused, or browser-mismatched state. |
| Callback | 400 | Authorization denied/cancelled, or no authorization code. |
| Callback | 502 | Token exchange failed or the provider response was invalid. |
| Callback | 503 | Connection could not be saved; start authorization again. |

Example:

```json
{
  "detail": "Invalid, expired or mismatched OAuth state"
}
```

Connection-list storage errors are not explicitly translated to a 503 by the
current route; unexpected storage errors may produce a 500 response. Backend
must handle non-JSON transport/server failures too. No automatic OAuth exchange
retry or recovery is implemented. Do not log codes, cookies, credentials, or
authorization URLs containing state.

## Local setup and verification

Run from `C:\workspace\chat\ai` in CMD. Docker Desktop must be running.

```bat
cd C:\workspace\chat\ai
.venv\Scripts\activate
python -m pip install -e ".[test]"
```

If the virtual environment is absent, create it with `python -m venv .venv`
using Python 3.11 or newer before activation. If `.env` is absent, copy
`.env.example` to `.env`. Configure these required values:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Example: `postgresql+psycopg://postgres:postgres@localhost:5432/find_ai`. |
| `AI_SERVICE_TOKEN` | Backend-shared secret, at least 16 characters. |
| `NOTION_CLIENT_ID` | Public connection OAuth client ID. |
| `NOTION_CLIENT_SECRET` | Public connection OAuth client secret. |
| `NOTION_REDIRECT_URI` | The registered browser-facing callback URL. |
| `TOKEN_ENCRYPTION_KEY` | Valid Fernet key, retained across restarts. |

Generate a local key with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Keep it local and do not include it in shared logs or screenshots.

```bat
docker compose up -d db
docker compose ps
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Wait for the database to be healthy and `Application startup complete.` in AI's
console. Startup creates missing AI tables. This runs `app`, not the independent
`src` implementation. No separate compilation step is required. Inspect
[Swagger UI](http://localhost:8001/docs) and
[runtime OpenAPI](http://localhost:8001/openapi.json) for generated schema details.

Run isolated automated tests with:

```bat
python -m pytest -q
```

Tests use mocked Notion HTTP responses and in-memory SQLite; they do not prove
live Notion or PostgreSQL integration. For a manual integration check:

1. Start authorization through Backend using a logged-in Chat session.
2. Confirm the browser has the HttpOnly OAuth cookie at the callback path.
3. Open the returned URL in the same browser and authorize selected Notion pages.
4. Confirm the callback returns connection metadata without tokens and deletes
   the OAuth cookie.
5. List connections through Backend for the same user and confirm the returned ID.
6. Repeat the callback URL: it must fail with 400. A new flow with a different
   browser lacking the cookie must also fail. Cancellation must not save a new
   connection; listing as another user must not reveal this user's connection.

For an AI-only test, use the AI callback URI, authorize the local Swagger UI with
the service token, invoke the start endpoint there, and open its returned URL in
the same browser. Do not distribute the service token to real frontend clients.
Avoid running simultaneous authorization flows in one browser: the cookie name
and path are shared and a later flow overwrites the browser-binding cookie.
