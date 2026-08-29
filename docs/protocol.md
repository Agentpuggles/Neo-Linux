# NeoFN launcher protocol reference

Everything the official Windows launcher (NeoLauncher 1.0.7, WinUI3 + Epic
BuildPatchServices) puts on the wire, reverse-engineered and **validated live**
against production (2026-08). This is the document `neo` was built from.

## 1. Services

| service | base URL |
|---|---|
| Account | `https://account-public-service-prod.neofn.dev/account` |
| Launcher | `https://launcher-public-service-prod06.neofn.dev/launcher` |
| Lightswitch | `https://lightswitch-public-service-prod.neofn.dev/lightswitch` |
| Prism | `https://prism-public-service-prod.neofn.dev/prism` |
| Fortnite (MCP) | `https://fortnite-public-service-prod11.neofn.dev/fortnite` |
| Content/news | `https://fortnitecontent-website-prod07.neofn.dev/content/api` |
| XMPP (friends) | `wss://xmpp-service-prod.neofn.dev` |
| Content CDN | from distribution points, e.g. `https://content-cdn.neofn.dev` |

OAuth client (the official launcher's own, Basic auth):
`8a4eeb89e05743fc9dba6fccb6766d35` / `7fe1392842624667b996d55ab5ebef03`.

## 2. Auth

### 2.1 Client credentials (anonymous calls)

```
POST /account/api/oauth/token      Authorization: Basic base64(id:secret)
grant_type=client_credentials
→ { access_token, expires_in: 14400, internal_client: true, client_service: "neo" }
```

### 2.2 Discord user login

```
1. Browser → GET /account/api/oauth/challenge/Discord    ← CASE-SENSITIVE route!
             ?clientId=<id>&redirectUri=neolauncher://callback/auth
   ("Discord" exactly; lowercase → HTTP 500 numericErrorCode 1012)
   → 302 https://discord.com/oauth2/authorize?client_id=1514333009892081846
        &scope=identify email guilds.members.read&response_type=code
        &redirect_uri=…/account/api/internal/callback&state=<signed blob>
2. User authorizes → backend → redirect neolauncher://callback/auth?code=<code>
   (Linux: xdg scheme handler, or paste the URL — both built into neo)
3. POST /account/api/oauth/token   (Basic auth)
   grant_type=authorization_code&authorization_code=<code>
                                          ^^^^^^^^^^^^^^^^^^
   ⚠️ the field is "authorization_code", NOT "code" (nonstandard; wrong field →
   400 common.oauth.invalid_request, right field + bad value →
   400 account.oauth.authorization_code_not_found)
→ { access_token, refresh_token, expires_at, refresh_expires_at,
    account_id, display_name }          (snake_case)
```

Refresh: `grant_type=refresh_token&refresh_token=<rt>` (refresh when < 5 min left).
Session hygiene: `DELETE /account/api/oauth/sessions/kill?killType=OTHERS_ACCOUNT_CLIENT`.

First-run setup: `GET api/public/account/setup/status` →
`GET api/public/account/displayName/{name}/available` (`{available: bool}`) →
`POST api/public/account/setup` JSON `{"displayName": "…"}` → returns the account.

Profile: `GET api/public/account/{accountId}`. Play-access gate:
`GET api/public/account/{id}/fortniteAccess`.

### 2.3 Exchange codes (game auth, every launch)

```
GET /account/api/oauth/exchange      (Bearer user token)
→ { code, expiresInSeconds }         — single use, short lived; two per launch
```

## 3. Status / gates

```
GET /lightswitch/api/service/fortnite/status     (Bearer client-credentials)
→ { serviceInstanceId: "fortnite", status: "UP", message, banned, allowedActions }
   (lowercase "status" — not Epic's IsUp)

GET /prism/api/v1/ban-status                     (Bearer user token)
→ { banned, reason }
```

## 4. Catalog & content

```
GET /launcher/api/public/builds                  (Bearer client-credentials)
→ [ { version: "++Fortnite+Release-10.40-CL-9380822", fileSizeBytes,
      releaseDate, isLive, manifestPath: "Builds/Fortnite/CloudDir/<name>.manifest" } ]

GET /launcher/api/public/distributionpoints
→ { distributions: [ "https://content-cdn.neofn.dev" ] }   (also: /releases, /onlinecount)
```

Manifest URL: `distributions[0] + "/" + build.manifestPath`. JSON, ~20 MB for 10.40.

## 5. Epic JSON manifest (BuildPatchServices)

Top-level: `ManifestFileVersion`, `bIsFileData`, `FileManifestList`, `ChunkHashList`,
`ChunkShaList`, `DataGroupList`, `ChunkFilesizeList`, `CustomFields`, `LaunchExeString`,
`CloudDirectories`…

**⚠️ All numerics are fixed-width zero-padded decimal strings ("blobs")** — never
`int()` them wholesale. Blob decode = 3 decimal digits per byte.

| field | meaning | decode |
|---|---|---|
| `ManifestFileVersion` | feature level, e.g. `"013000000000"` | first 3 digits = FL (13) |
| `ChunkHashList[g]` | rolling hash | 24 digits → 8 bytes, **little-endian** u64 |
| `ChunkShaList[g]` | SHA-1 | 60 digits → 20 bytes, as-is |
| `DataGroupList[g]` | group number | **plain int** (not a blob) |
| `ChunkFilesizeList[g]` | compressed size | plain int |
| `FileChunkParts[i]` | `{Guid, Offset, Size}` | plain ints |

`FileManifestList[i]` = `{ Filename, FileHash, FileChunkParts[], bIsUnixExecutable,
SymlinkTarget }`. Files assemble by concatenating chunk slices; empty files have zero
parts.

## 6. Chunk storage

From `FBuildPatchAppManifest.GetDataFilename` (decompiled BuildPatchServices.dll):

```
FL >= DataFileRenames:
  {ChunksV2|V3|V4}/{group:D2}/{rollingHash:X16}_{GUID}.chunk
  subdir: FL<6 ChunksV2 · FL<15 ChunksV3 · FL>=15 ChunksV4
  group = DataGroupList value (raw; fallback crc32(guid)%100)
  rollingHash = ChunkHashList blob decoded to u64 (LE), formatted %016X
  GUID = 32 uppercase hex ("N" format)
FL < DataFileRenames:
  Chunks/{crc32(guid)%100:D2}/{GUID}.chunk
```

Chunks live under `<dist>/Builds/Fortnite/CloudDir/`. FL 13 (all current builds) →
`ChunksV3`. Example (validated):
`…/ChunksV3/31/487A33F0F2E5F569_1832294A440167B074AC75B6A842F82A.chunk`

### Chunk file format (v2 header, 62 B)

```
u32 magic 0xB1FE3AA2 · u32 version · u32 headerSize(62) · u32 dataSizeCompressed
16 B GUID (MS mixed-endian) · u64 rollingHash · u8 storedAs@40 · sha1[20]@41 ·
u8 hashType@60 → payload at headerSize
```

- payload is a zlib stream iff `storedAs & 1`; uncompressed size = 1 MiB (v3+ headers
  carry `dataSizeUncompressed@62` — always trust `headerSize` over fixed offsets)
- the header SHA-1 covers the **uncompressed** payload and must equal `ChunkShaList[g]`
- verify `rollingHash` == `ChunkHashList[g]` for extra paranoia

### CDN gotchas (Cloudflare R2)

- answers **403 to python-urllib's default UA** — send a custom User-Agent
- the edge **transiently 404s existing objects** — retry with backoff
- no bucket listing, no directory index

## 7. Prism (patched client)

```
GET /prism/api/assets         (Bearer user token)
→ [ { filename, hash256, size, contentType, uploadedAt, url } ]
```

Download all assets to the launcher data dir, sha256-verify each, re-download on
mismatch. Currently ships `FortniteClient-Win64-Shipping.exe` (patched client),
`NeoPrism.Agent.exe`, `NeoPrism.Bootstrapper.exe`. The patched exe redirects Epic
hostnames to NeoFN services (verified in-game: requests aimed at
`account-public-service-prod.ol.epicgames.com` are served by neofn.dev).

## 8. Launch recipe (exact — `GameLauncher.LaunchAsync`)

Executable: prism-patched `FortniteClient-Win64-Shipping.exe`.
Working dir: `<install>/<version>/FortniteGame/Binaries/Win64` (must contain the
vanilla build's exe).

```
-basedir="<that Win64 dir>"
-epicapp=Fortnite -epicenv=Prod -epicportal -skippatchcheck -nobe -fromfl=eac
-AUTH_LOGIN=unused -AUTH_TYPE=exchangecode -AUTH_PASSWORD=<exchange code 1>
-p=<exchange code 2>
-fltoken=<random 24 chars [a-z0-9]>
```

`-p` is prism's code (the decompile names it *prismCode*). Preconditions checked
first: lightswitch UP, not banned (both services), assets present, 2 fresh exchange
codes.

### Linux notes (umu-run / Proton)

- On Windows the args form one raw command line. Through umu→Wine, argv is rebuilt
  and **embedded quotes get escaped** — pass `-basedir` bare (no quotes) or UE4's
  parser leaves a stray backslash → *"Failed to open descriptor file"*.
- Unix install paths map into Wine as `Z:\<path>`; don't double the backslash after
  the drive letter. If the install is inside the prefix's `drive_c`, use `C:\…`.
- The game is DX11; umu-run + any modern Proton works. Logs land at
  `<prefix>/drive_c/users/<user>/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log`.

## 9. Login flow inside the game (observed)

Exchange code → `StartLogin` → "Signing in to Epic services" (URL nominally Epic's,
served by neofn.dev) → kill-sessions 204 → `Successfully logged in user` →
`CheckPlatformPlayAllowed` → `CheckServiceAvailability` → `CheckEntitledToPlay`
(`QueryAvailableFeature`); a `missing_action 'PLAY'` rejection triggers
`OnGrantFreeAccess` (auto-grant flow) then re-check — on failure, ForceLogout to the
email/password fallback screen. I.e. a login screen usually means *entitlement*, not
*authentication*, trouble.
