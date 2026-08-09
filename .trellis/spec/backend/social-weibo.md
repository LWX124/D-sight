# Weibo Social Integration

## 1. Scope / Trigger

Use this contract when changing the Weibo credential, account preview, subscription, snapshot ingestion, scheduler, frontend API, or Agent query flow. The integration reads undocumented mobile-web endpoints with an administrator-managed session, so upstream payloads are untrusted and the feature has no availability SLA.

## 2. Signatures

- Credential API: `GET|PUT|DELETE /api/social/weibo/credential`
- Account API: `POST /api/social/weibo/accounts/preview`
- Subscription API: `POST|GET /api/social/weibo/subscriptions`, `DELETE /api/social/weibo/subscriptions/{id}`
- Content API: `GET /api/social/weibo/posts`, `POST /api/social/weibo/refresh`
- Scheduler: `weibo_poll`, every `WEIBO_POLL_MINUTES` (default 60), `max_instances=1`, `coalesce=True`
- Agent tool: `make_weibo_query(session_factory, user_id)` → `weibo_query(account, keyword, days, limit)`
- DB tables: `weibo_credentials`, `weibo_accounts`, `weibo_posts`, `weibo_subscriptions`

## 3. Contracts

- `PUT /credential` accepts `{cookies: string}`. Business validation trims input, rejects empty values, CR/LF, and values over 16 KiB. Validate upstream before Fernet encryption. Never return or log the Cookie.
- `POST /accounts/preview` accepts an HTTP(S) Weibo profile URL with an explicit numeric UID. It returns normalized account metadata and an internal `account_id`.
- `POST /subscriptions` accepts `{account_id}`. A new subscription and its initial snapshots are one transaction. The instance may have at most `WEIBO_MAX_ACCOUNTS` distinct enabled accounts (default 20).
- `GET /posts` returns only the current user's subscribed account snapshots. Media items are `{type: "image" | "video", url, poster_url?}`.
- `weibo_posts(account_id, external_id)` is unique. Existing rows are immutable capture-time snapshots.
- The upstream module owns JSON validation and exposes normalized `WeiboProfile` and `RawWeiboPost`; API, DB, frontend, and Agent code must not parse raw Weibo payloads.
- `WEIBO_FETCH_COUNT=20`, `WEIBO_MAX_PAGES=3`, `WEIBO_GLOBAL_COOLDOWN_MINUTES=1440`, and platform-specific Redis keys bound each polling round.

## 4. Validation & Error Matrix

| Condition | Behavior |
|---|---|
| Non-admin writes credential | HTTP 403 |
| Cookie empty, too large, or contains CR/LF | HTTP 422 with generic text; never echo input |
| Cookie/login expired (`ok=-100`) | HTTP 409; credential becomes `expired`; stop polling round |
| Upstream HTTP 403/432 | HTTP 429 + `Retry-After`; credential becomes `blocked`; trip global cooldown; stop round |
| Upstream timeout, 5xx, or invalid account payload | HTTP 503; scheduled polling isolates the account |
| Invalid profile host/path/UID | HTTP 422 before any upstream request |
| Instance account limit reached | HTTP 409 |
| User reads/refreshes an unsubscribed account | HTTP 403 |
| New subscription initial sync fails | Roll back subscription and snapshots; persist only account error state |

## 5. Good / Base / Bad Cases

- Good: an admin saves a valid dedicated Cookie, a user previews a numeric-UID profile, confirms it, receives up to 20 original snapshots, and later polling inserts only unseen IDs.
- Base: polling sees an existing non-pinned post and stops pagination; existing snapshots remain unchanged even if upstream content changed.
- Bad: an existing pinned post precedes new posts. The parser marks it pinned, and ingestion must not treat it as the incremental stop boundary.
- Bad: Redis is unavailable. Cooldown checks fail open with a warning, but secrets are not logged and upstream errors still map through the typed error layer.

## 6. Tests Required

- Parser: profile/container validation, HTML-to-text, original/repost, pinned status, long content, media, timestamps, malformed payloads.
- Client: valid login, `ok=-100`, 403/432, 5xx, timeout, and non-JSON.
- Credential/API: admin guard, Cookie encryption/no echo, URL validation, subscription ownership, global limit, and failed-initial-sync rollback.
- Ingestion/job: first 20 originals, immutable dedupe, pinned boundary, global cooldown short circuit, session/rate-limit round stop, transient account isolation.
- Tests that assert instance-global account counts or scheduler totals must explicitly clear `weibo_subscriptions` first because the session-scoped PostgreSQL fixture intentionally persists data across test cases.
- Agent: user subscription isolation and account/keyword/time/limit filters; no upstream call.
- Frontend: platform tab, credential role/status, preview/confirm, cooldown/error status, list/detail/media.
- Migration: single Alembic head plus upgrade/downgrade; PostgreSQL integration tests are required before production deployment.

## 7. Wrong vs Correct

### Wrong

```python
db.add(subscription)
await db.commit()
await ingest_account(db, account, credential, initial=True)
```

If ingestion fails, the API returns an error but leaves a subscription behind. An idempotent retry then skips the initial sync.

### Correct

```python
db.add(subscription)
await db.flush()
try:
    await ingest_account(db, account, credential, initial=True)  # commits snapshots + subscription
except UpstreamError:
    await db.rollback()
    raise
```

Keep the subscription and initial snapshot write atomic. Error-state persistence starts a new transaction only after the failed write transaction has rolled back.
