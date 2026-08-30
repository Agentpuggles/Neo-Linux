# NeoFN launcher protocol reference

Everything the official Windows launcher (**NeoLauncher 1.0.7**, WinUI3 + Epic
BuildPatchServices) puts on the wire — reverse-engineered from the decompiled
binaries and **validated live against production (2026-08)**. This is the document
[`neo`](../neo) was built from.

Where a section describes a wire format, the corresponding Python implementation is
named in its heading (e.g. `parse_num`, `parse_chunk`) so the doc and the code stay
side by side.

## Contents

| § | Section | Covers |
| --- | --- | --- |
| 1 | [Services](#1-services) | Base URLs, OAuth client |
| 2 | [Auth](#2-auth) | Client credentials, Discord login, session upkeep, exchange codes |
| 3 | [Status and gates](#3-status-and-gates) | Lightswitch, ban status |
| 4 | [Catalog and distribution points](#4-catalog-and-distribution-points) | Build list, CDN roots |
| 5 | [Epic JSON manifest](#5-epic-json-manifest) | BuildPatchServices manifest format, decimal "blob" numerics |
| 6 | [Chunk storage](#6-chunk-storage) | Chunk URL scheme, 62-byte file format, CDN gotchas |
| 7 | [Prism (patched client)](#7-prism-patched-client) | Asset list, sha256 verification, exe patching |
| 8 | [Launch recipe](#8-launch-recipe) | Exact command line, Wine/umu-run notes |
| 9 | [In-game login flow](#9-in-game-login-flow-observed) | What happens after the exchange code |
| 10 | [Known ambiguities](#10-known-ambiguities) | Where the format leaves room for misreads |
| 11 | [Launcher self-update and access gating](#11-launcher-self-update-and-access-gating) | Velopack feed & schedule, playability gates, store entitlements |
| 12 | [Friends over XMPP: scoping notes](#12-friends-over-xmpp-scoping-notes) | What a `neo friends` would take, read from the client |

## Gotchas at a glance

| # | Gotcha | § |
| --- | --- | --- |
| 1 | The Discord challenge route is **case-sensitive**: `/challenge/Discord`, never `/challenge/discord` | [2.2](#22-discord-user-login) |
| 2 | The token request field is **`authorization_code`**, not the OAuth-standard `code` | [2.2](#22-discord-user-login) |
| 3 | Manifest numerics are **fixed-width decimal strings** — never `int()` them wholesale | [5](#5-epic-json-manifest) |
| 4 | `DataGroupList` is a **plain int**, unlike its blob-encoded neighbours | [5](#5-epic-json-manifest) |
| 5 | A chunk's header SHA-1 covers the **uncompressed** payload | [6.2](#62-chunk-file-format-v2-header-62-b) |
| 6 | Trust `headerSize` over fixed offsets; v3+ headers are longer | [6.2](#62-chunk-file-format-v2-header-62-b) |
| 7 | R2 answers **403 to python-urllib's default User-Agent** | [6.3](#63-cdn-gotchas-cloudflare-r2) |
| 8 | The R2 edge **transiently 404s objects that exist** — retry with backoff | [6.3](#63-cdn-gotchas-cloudflare-r2) |
| 9 | Through umu→Wine, **embedded quotes get escaped** — pass `-basedir` bare | [8.1](#81-linux-notes-umu-run--proton) |
| 10 | An in-game login screen usually means **entitlement**, not authentication | [9](#9-in-game-login-flow-observed) |
| 11 | The web UI checks `fortniteAccess` **once per start**; the refresh event is never re-dispatched — a grayed Launch button needs a launcher restart | [11.2](#112-playability-gates) |
| 12 | The public-build allowlist (`["10.40"]`) is baked into **both** the DLL and the web bundle — a new public build ships as a launcher update | [11.2](#112-playability-gates) |

---

## 1. Services

| Service | Base URL |
| --- | --- |
| Account | `https://account-public-service-prod.neofn.dev/account` |
| Launcher | `https://launcher-public-service-prod06.neofn.dev/launcher` |
| Lightswitch | `https://lightswitch-public-service-prod.neofn.dev/lightswitch` |
| Prism | `https://prism-public-service-prod.neofn.dev/prism` |
| Fortnite (MCP) | `https://fortnite-public-service-prod11.neofn.dev/fortnite` |
| Content / news | `https://fortnitecontent-website-prod07.neofn.dev/content/api` |
| Store / entitlements | `https://store.neofn.dev/api/v1` |
| Analytics | `https://analytics-public-service-prod.neofn.dev/analytics` |
| XMPP (friends) | `wss://xmpp-service-prod.neofn.dev` |
| Content CDN | from distribution points, e.g. `https://content-cdn.neofn.dev` |

OAuth client — the official launcher's own, used with HTTP Basic auth:

| Field | Value |
| --- | --- |
| `client_id` | `8a4eeb89e05743fc9dba6fccb6766d35` |
| `client_secret` | `7fe1392842624667b996d55ab5ebef03` |

## 2. Auth

### 2.1 Client credentials (anonymous calls)

```http
POST /account/api/oauth/token        Authorization: Basic base64(id:secret)
grant_type=client_credentials
```

```json
{ "access_token": "…", "expires_in": 14400,
  "internal_client": true, "client_service": "neo" }
```

### 2.2 Discord user login

```
1. Browser → GET /account/api/oauth/challenge/Discord      ← CASE-SENSITIVE route!
             ?clientId=<id>&redirectUri=neolauncher://callback/auth
   ("Discord" exactly; lowercase → HTTP 500, numericErrorCode 1012)
   → 302 https://discord.com/oauth2/authorize?client_id=1514333009892081846
        &scope=identify email guilds.members.read&response_type=code
        &redirect_uri=…/account/api/internal/callback&state=<signed blob>

2. User authorizes → backend → neolauncher://callback/auth?code=<code>
   (Linux: an xdg scheme handler, or paste the URL — both built into neo)

3. POST /account/api/oauth/token                           (Basic auth)
   grant_type=authorization_code&authorization_code=<code>
                                          ^^^^^^^^^^^^^^^^^
   ⚠️  the field is "authorization_code", NOT "code" (nonstandard).
       wrong field → 400 common.oauth.invalid_request
       right field, bad value → 400 account.oauth.authorization_code_not_found
```

Response (note the snake_case keys):

```json
{ "access_token": "…", "refresh_token": "…",
  "expires_at": "…", "refresh_expires_at": "…",
  "account_id": "…", "display_name": "…" }
```

### 2.3 Session upkeep

| Operation | Request |
| --- | --- |
| Refresh | `grant_type=refresh_token&refresh_token=<rt>` — refresh when under 5 min remain |
| Kill other sessions | `DELETE /account/api/oauth/sessions/kill?killType=OTHERS_ACCOUNT_CLIENT` |

### 2.4 First-run setup

```
GET  api/public/account/setup/status
GET  api/public/account/displayName/{name}/available      → { available: bool }
POST api/public/account/setup        JSON {"displayName": "…"}   → the account
```

### 2.5 Profile and play access

```
GET api/public/account/{accountId}
GET api/public/account/{accountId}/fortniteAccess        ← the play-access gate
```

### 2.6 Exchange codes (game auth, every launch)

```http
GET /account/api/oauth/exchange                          (Bearer user token)
```

```json
{ "code": "…", "expiresInSeconds": 300 }
```

Single use, short lived; **two** are minted per launch.

## 3. Status and gates

```http
GET /lightswitch/api/service/fortnite/status             (Bearer client credentials)
```

```json
{ "serviceInstanceId": "fortnite", "status": "UP",
  "message": "…", "banned": false, "allowedActions": ["…"] }
```

Lowercase `status` — not Epic's `IsUp`.

```http
GET /prism/api/v1/ban-status                             (Bearer user token)
```

```json
{ "banned": false, "reason": null }
```

## 4. Catalog and distribution points

```http
GET /launcher/api/public/builds                          (Bearer client credentials)
```

```json
[ { "version": "++Fortnite+Release-10.40-CL-9380822",
    "fileSizeBytes": 0, "releaseDate": "…", "isLive": true,
    "manifestPath": "Builds/Fortnite/CloudDir/<name>.manifest" } ]
```

```http
GET /launcher/api/public/distributionpoints
```

```json
{ "distributions": ["https://content-cdn.neofn.dev"] }
```

Also available on the same service: `/releases`, `/onlinecount`.

The manifest URL is `distributions[0] + "/" + build.manifestPath` — JSON, roughly
20 MB for 10.40.

## 5. Epic JSON manifest

Top-level keys:

| Key | Meaning |
| --- | --- |
| `ManifestFileVersion` | Feature level, e.g. `"013000000000"` |
| `bIsFileData` | Whether file payloads are in the manifest |
| `FileManifestList` | One entry per file |
| `ChunkHashList` | Rolling hash per chunk GUID |
| `ChunkShaList` | SHA-1 per chunk GUID |
| `DataGroupList` | Data group per chunk GUID |
| `ChunkFilesizeList` | Compressed size per chunk GUID |
| `CustomFields`, `LaunchExeString`, `CloudDirectories` | Misc |

### 5.1 Numerics: fixed-width decimal "blobs"

> ⚠️ **Most numerics in this format are zero-padded decimal strings, not JSON
> numbers.** Never `int()` them wholesale. Decoding a blob = three decimal digits
> per byte, read little-endian where the field is a multi-byte integer.

| Field | Meaning | Encoding | Decode |
| --- | --- | --- | --- |
| `ManifestFileVersion` | Feature level | blob | first 3 digits = FL (13) |
| `ChunkHashList[g]` | Rolling hash | blob | 24 digits → 8 bytes, **little-endian** u64 |
| `ChunkShaList[g]` | SHA-1 | blob | 60 digits → 20 bytes, as-is |
| `DataGroupList[g]` | Data group | **plain int** | `int(value)`, leading zeros stripped |
| `ChunkFilesizeList[g]` | Compressed size | blob **or** plain | `neo.parse_num` accepts both |
| `FileChunkParts[i]` | `{Guid, Offset, Size}` | blob **or** plain | `neo.parse_num` accepts both |

`neo` resolves the ambiguity by length: a digit string whose length is a multiple of
three **and greater than three** is a blob, anything else is a plain int. See
[§10](#10-known-ambiguities) for where that heuristic can bite.

Verified against `neo.parse_num`:

| Input | Result | Why |
| --- | --- | --- |
| `"031"` | `31` | 3 digits → treated as a plain group number |
| `"00000000063"` | `63` | 11 digits, not a multiple of 3 → plain int |
| `"000001"` | `256` | 6 digits → blob, 2 bytes LE |
| `63` (int) | `63` | already numeric |
| `"1048576"` | `1048576` | 7 digits, not a multiple of 3 → plain |

### 5.2 File manifest entries

```json
{ "Filename": "…", "FileHash": "…",
  "FileChunkParts": [ { "Guid": "…", "Offset": "…", "Size": "…" } ],
  "bIsUnixExecutable": false, "SymlinkTarget": null }
```

Files assemble by concatenating chunk slices in order. Empty files carry zero parts.
`FileHash` is the SHA-1 of the assembled file; `bIsUnixExecutable` maps to mode
`0755`; `SymlinkTarget` is honoured instead of writing a file.

## 6. Chunk storage

### 6.1 Chunk URLs

From `FBuildPatchAppManifest.GetDataFilename` (decompiled BuildPatchServices.dll):

```
FL >= DataFileRenames:
    {ChunksV2|ChunksV3|ChunksV4}/{group:02d}/{rollingHash:016X}_{GUID}.chunk

    subdir        FL < 6 → ChunksV2 · FL < 15 → ChunksV3 · FL >= 15 → ChunksV4
    group         DataGroupList value (raw; fallback crc32(guid) % 100)
    rollingHash   ChunkHashList blob decoded to u64 (LE), formatted %016X
    GUID          32 uppercase hex characters (the "N" format)

FL < DataFileRenames:
    Chunks/{crc32(guid) % 100:02d}/{GUID}.chunk
```

Chunks live under `<dist>/Builds/Fortnite/CloudDir/`. Every current build is FL 13,
i.e. `ChunksV3`. Validated example:

```
…/ChunksV3/31/487A33F0F2E5F569_1832294A440167B074AC75B6A842F82A.chunk
```

`neo` tries the `ChunksV3` form first and falls back to the `ChunksV4` layout
(`ChunksV4/{guid[:2]}/{guid}.chunk`) when the manifest's feature level disagrees
with what the CDN actually serves.

### 6.2 Chunk file format (v2 header, 62 B)

```
offset  size  field
0       4     u32 magic          0xB1FE3AA2
4       4     u32 version
8       4     u32 headerSize     62 for v2
12      4     u32 dataSizeCompressed
16      16    GUID (MS mixed-endian)
32      8     u64 rollingHash
40      1     u8  storedAs
41      20    u8[20] sha1
60      1     u8  hashType
62      …     payload
```

- The payload is a zlib stream **iff** `storedAs & 1`; uncompressed size is 1 MiB.
- v3+ headers carry `dataSizeUncompressed` at offset 62 — always trust `headerSize`
  over fixed offsets.
- The header SHA-1 covers the **uncompressed** payload and must equal
  `ChunkShaList[g]`.
- For extra paranoia, also check `rollingHash` == `ChunkHashList[g]`.

`neo.parse_chunk` implements exactly this layout and verifies the SHA-1 against the
manifest before a chunk is accepted.

### 6.3 CDN gotchas (Cloudflare R2)

| Gotcha | Handling |
| --- | --- |
| **403 for python-urllib's default User-Agent** | `neo` sends `neo-linux/<version>` |
| The edge **transiently 404s objects that exist** | retry with backoff |
| No bucket listing, no directory index | fetch by exact object key only |

## 7. Prism (patched client)

```http
GET /prism/api/assets                                    (Bearer user token)
```

```json
[ { "filename": "…", "hash256": "…", "size": 0,
    "contentType": "…", "uploadedAt": "…", "url": "…" } ]
```

Download every asset into the launcher data dir, sha256-verify each, re-download on
mismatch. Currently shipped:

| Asset | Role |
| --- | --- |
| `FortniteClient-Win64-Shipping.exe` | Patched client — required |
| `NeoPrism.Agent.exe` | Best-effort |
| `NeoPrism.Bootstrapper.exe` | Best-effort |

The patched exe redirects Epic hostnames to NeoFN services: verified in-game,
requests aimed at `account-public-service-prod.ol.epicgames.com` are served by
neofn.dev.

## 8. Launch recipe

Exact reproduction of `GameLauncher.LaunchAsync`.

| | |
| --- | --- |
| **Executable** | prism-patched `FortniteClient-Win64-Shipping.exe` |
| **Working dir** | `<install>/<version>/FortniteGame/Binaries/Win64` (must contain the vanilla build's exe) |

```
-basedir=<that Win64 dir>
-epicapp=Fortnite -epicenv=Prod -epicportal -skippatchcheck -nobe -fromfl=eac
-AUTH_LOGIN=unused -AUTH_TYPE=exchangecode -AUTH_PASSWORD=<exchange code 1>
-p=<exchange code 2>
-fltoken=<random 24 chars [a-z0-9]>
```

`-p` is prism's code — the decompile names it *prismCode*. Preconditions checked
first, in order: lightswitch `UP`, not banned (both services), prism assets present,
two fresh exchange codes minted.

### 8.1 Linux notes (umu-run / Proton)

- On Windows the arguments form one raw command line. Through umu→Wine, argv is
  rebuilt and **embedded quotes get escaped** — pass `-basedir` bare (no quotes), or
  UE4's parser leaves a stray backslash and fails with *"Failed to open descriptor
  file"*.
- Unix install paths map into Wine as `Z:\<path>`; don't double the backslash after
  the drive letter. If the install sits inside the prefix's `drive_c`, use `C:\…`
  instead.
- The game is DX11; umu-run plus any modern Proton works. Logs land at
  `<prefix>/drive_c/users/<user>/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log`.

## 9. In-game login flow (observed)

```
exchange code
  → StartLogin
  → "Signing in to Epic services"   (URL nominally Epic's, served by neofn.dev)
  → kill-sessions 204
  → "Successfully logged in user"
  → CheckPlatformPlayAllowed
  → CheckServiceAvailability
  → CheckEntitledToPlay  (QueryAvailableFeature)
       └─ missing_action 'PLAY' → OnGrantFreeAccess (auto-grant) → re-check
       └─ still failing → ForceLogout to the email/password fallback screen
```

So a login screen at this point usually means an **entitlement** problem, not an
**authentication** one.

## 10. Known ambiguities

The format leaves a few places where a value's encoding can only be guessed from its
shape:

| Case | Risk |
| --- | --- |
| A 3-digit decimal string | Indistinguishable from a 1-byte blob. `neo` treats 3 digits as a plain int, so `DataGroupList` group numbers decode correctly. |
| A plain int with 6, 9 or 12 digits | Its length is a multiple of 3, so it is misread as a blob. Verified: a plain `"100000000"` (100 MB) decodes to `100`. Not observed in current manifests, but unguarded. |
| `ChunkFilesizeList` / `FileChunkParts` | Appear as plain ints in the manifests seen so far; `neo.parse_num` accepts either form so both parse. |

These are recorded rather than resolved: current builds (FL 13) parse correctly end
to end, per the validated 10.40 install recorded in the README's status table.

## 11. Launcher self-update and access gating

Read out of NeoLauncher 1.0.7 itself — the `NeoLauncher.dll` managed code plus
the bundled `web/` WebView2 app it hosts — and cross-checked against the
on-disk Velopack layout (`Update.exe`, `current/`, `packages/`). Answers the
two questions the wire format alone cannot: *how does the launcher update, and
what decides who is allowed to play?*

### 11.1 Self-update (Velopack)

```http
GET /launcher/api/public/releases             (Bearer client credentials)
```

`NeoUpdateSource` maps this feed into a `Velopack.VelopackAssetFeed` and hands
it to `Velopack.UpdateManager`; `sq.version` beside `Update.exe` is Velopack's
local manifest (id `NeoLauncher`, channel `win`, current version). Packages are
full `.nupkg`s — `packages/NeoLauncher-1.0.7-full.nupkg` — no deltas observed.

| When | What happens |
| --- | --- |
| startup | update check runs immediately |
| every 30 min | `System.Threading.Timer` re-check (`LauncherUpdateInterval`) |
| window activated | re-check, throttled to ≥5 min apart |
| update found | downloaded automatically **unless** the game is running or a build is installing, then applied and the launcher **restarts itself** (`ApplyUpdatesAndRestart`) |

State machine `idle → checking → upToDate | available → downloading → ready`,
pushed to the web UI as the `neo-launcher-update-changed` event; Settings has a
manual check (`checkLauncherUpdate` / `applyLauncherUpdate`). Because the web
UI ships inside the package, UI changes ride the same channel.

### 11.2 Playability gates

Three gates — and, for the record, **no launch date or countdown logic exists
anywhere** in the host or the web bundle (no date constants, no `DateTime`
comparisons, no countdown code):

1. **Per-account client gate.**
   `GET /account/api/public/account/{id}/fortniteAccess` answers the literal
   body `true` or `false`. On `false` the launcher refuses to launch with
   *"No Access — Your account doesn't have access to Neo. Neo is in private
   testing. Check the discord for more information."* The web UI fetches it
   once at mount (`get_fortnite_access`) and caches it; the host never
   re-dispatches the refresh event, so a grayed Launch button stays gray until
   the launcher restarts (see gotcha 11). `neo launch` never consults this
   gate — `neo status` prints it.
2. **Baked-in build allowlist.** `PublicBuildVersions = ["10.40"]`, with a
   3-account `DeveloperAccountIds` override, is hardcoded in *both* the DLL and
   the web bundle (`const eM=["10.40"]`). Installing anything else is refused:
   *"This build is currently unavailable on this account."* Consequence: a new
   public build must ship as a launcher update first — the 30-minute timer
   above rolls it out.
3. **The in-game `PLAY` entitlement** ([§9](#9-in-game-login-flow-observed)) —
   the server-side switch that actually opens the game. Nothing launcher-side
   is required when it flips; the same command line just starts working.

### 11.3 Store entitlements

```http
GET https://store.neofn.dev/api/v1/entitlements/{accountId}    (Bearer user token)
```

```json
{ "ownedOfferIds": ["5"],
  "orders": [ { "offerId": "5", "subscriptionId": null, "paid": true, "refunded": false } ],
  "subscriptions": [] }
```

Field set per the client's DTOs (`AccountEntitlementsDto`, parsed
case-insensitively); purchases — early access, supporter tiers — land here as
paid orders, and the launcher derives an account tier from them
(`getAccountTier`). `neo status` (v0.3.0) prints a one-line summary so a
purchase can be watched registering on the account without the Windows client.

### 11.4 WebView2 bridge (selected commands)

The WinUI 3 window hosts the bundled `web/` app; `NeoWebBridge` exposes ~60
commands over it. Notable: `launch_neo_build`, `import_neo_build`,
`migrate_neo_library`, `get_builds`, `get_neo_server_status` (polled every
15 s), `getServicesState` (every 30 s and on focus), `get_fortnite_access`,
`getAccountTier`, `checkLauncherUpdate`, `applyLauncherUpdate`. The host pushes
`neo-*` DOM events back (`neo-launcher-update-changed`,
`neo-game-state-changed`, `neo-service-builds-updated`, …).

## 12. Friends over XMPP: scoping notes

Scoped from the decompiled client and implemented in `neo` as **`neo friends`**
(v0.5.0) — validated against a scripted server; the live handshake still wants
one on-line confirmation from a logged-in machine (`neo friends -v`).

The official client does not use a library for this: `NeoLauncher.dll` contains a
hand-rolled XMPP client (`NeoLauncher.Services.Friends.NeoXmppClient`, 35 methods)
speaking raw XML stanzas over a websocket.

### 12.1 What the client does

| Piece | Observed in the binary |
| --- | --- |
| Transport | websocket to `wss://xmpp-service-prod.neofn.dev` (`NeoPresenceService.EnsureConnectedAsync`), **requesting subprotocol `xmpp`** (`AddSubProtocol("xmpp")`) — the edge answers `400 Bad Request` without it (found live; fixed in `neo` 0.5.2) |
| Session flow | `ConnectAsync` → `OpenStreamAsync` (RFC 7395 `<open>`/`<close>` framing) → `AuthenticateAsync` (SASL PLAIN) → `BindAsync` (`urn:ietf:params:xml:ns:xmpp-bind`) → `EstablishSessionAsync` (`xmpp-session`) → `RequestRosterAsync` (`jabber:iq:roster`) |
| Bind resource | `neo_launcher_bind_{n}` (interlocked counter), presence resource `"launcher"` |
| Auth | SASL **PLAIN** (`\x00authcid\x00password`, base64): authcid = **account id**, password = the **account access token** (`GetFriendsAccessTokenAsync` just calls `AccountService.GetAccessTokenAsync` — there is no separate friends token) |
| Events | `RawStanzaReceived` / `PresenceReceived` / `MessageReceived` / `Disconnected`; `LastInboundXml`/`LastOutboundXml` kept for debugging |
| Presence model | `NeoPresenceView`: accountId, status, activity, gameStatus, resource, resourceType, priority; lifecycle published as the game starts/stops |
| HTTP side | friends service `https://friends-public-service-prod.neofn.dev/friends` for roster/search/actions (add/remove, nicknames), so not everything needs XMPP; the roster call is `GET /api/public/friends/{id}?includePending=true` |

### 12.2 What `neo friends` would take

1. A websocket client on the standard library only: RFC 6455 handshake (`http.client`+
   `socket`+ `ssl` + `base64` for the key, then a frame codec — client frames are
   never masked server-side, so the codec is small). ~150 lines, testable against
   a local socket pair.
2. ~~Unknown~~ resolved: SASL **PLAIN**, authcid = account id, password = the
   account access token (confirmed against the IL: `username`/`token` fields are
   fed from `accountId` and `accessToken` at the `ConnectAsync` call site). The
   remaining live-confirm items: whether the server requires the official bind
   resource pattern, and the friends-REST payload shapes.
3. Roster + presence state tracking, which the HTTP endpoints may make unnecessary
   for a read-only `neo friends` listing (roster over HTTP, presence over XMPP).
4. A decision on backgrounding: presence publishing implies staying connected for
   the session; a listing command can connect, snapshot, and disconnect.

Risk notes: the server may reject non-official bind resources or token types; and
presence storms from polling reconnects would be antisocial — a snapshot client
avoids both.

### 12.3 Implementation (`neo friends`, v0.5.0)

A ~10% RFC 6455 client (masked frames, ping/pong, fragmentation, extended
lengths) plus the session above: open → PLAIN → re-open → bind
(`neo_launcher_bind_1`, the official pattern) → session → roster iq →
`<presence/>` → gather for `--wait` seconds (default 3) → unavailable → close.
Display names come from the batch public-profile endpoint; if the websocket is
unreachable the command falls back to `GET /friends/api/public/friends/{id}`
(no presence). `NEO_XMPP` overrides the endpoint (plain `ws://` works, e.g. for
a capture proxy). `--verbose` prints every stanza both ways — that output is
the fastest way to correct this section against the live service.
