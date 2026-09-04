# Engineering notes: failures, diagnoses, fixes

A candid log of every significant bug, dead end, and misdiagnosis from building neo,
with the reasoning that resolved each one. Written up for two reasons: the *methods*
here generalize to any reverse-engineering / interop project, and the *specifics*
(precedent for anyone else poking at NeoFN or Epic's BuildPatchServices format).

These notes were taken during the same AI-assisted sessions that produced `neo` (see
[README → Acknowledgements](../README.md#acknowledgements)). The first-person plural is
a human operator and the agents they were directing; the diagnoses were checked against
production and against the decompiled client, not against a model's confidence.

The recurring theme, if you want the one-paragraph version: **stop guessing, get
ground truth** — from the decompiled binary, the wire, or the game's own logs. Every
hard problem in this project fell within minutes of obtaining the right ground truth,
and every long detour was a period of working from assumptions instead.

Release-by-release summary: [CHANGELOG.md](../CHANGELOG.md).
Wire formats referenced below: [protocol.md](protocol.md).

## Contents

Each note below is a failure that cost real time, the diagnosis that ended it, and the line of `neo` or of the docs it turned into. Reading order does not matter; § links below jump to the note.

| § | Note | What it taught us |
| --- | --- | --- |
| 1 | [1. The launcher wouldn't run under Wine at all — pivot](#1-the-launcher-wouldnt-run-under-wine-at-all--pivot) | emulating a WinUI3 GUI is harder than replacing the logic under it |
| 2 | [2. The chunk-URL guessing marathon](#2-the-chunk-url-guessing-marathon) | never guess a CDN layout with no listing — read the shipped DLL |
| 3 | [3. Manifest numerics: the fixed-width decimal "blob" trap](#3-manifest-numerics-the-fixed-width-decimal-blob-trap) | length decides blob vs plain int; `int()` on the wrong one corrupts silently |
| 4 | [4. The 404 that wasn't (misdiagnosed our own bug as CDN flakiness)](#4-the-404-that-wasnt-misdiagnosed-our-own-bug-as-cdn-flakiness) | suspect your own parser before blaming the network |
| 5 | [5. Structural edit corrupted the script (duplicate tail)](#5-structural-edit-corrupted-the-script-duplicate-tail) | a bad copy/paste tail is real: compile and diff after every structural edit |
| 6 | [6. Login, part 1: the case-sensitive route that returned 500](#6-login-part-1-the-case-sensitive-route-that-returned-500) | a 500 can be a case-sensitive route, not an outage |
| 7 | [7. Login, part 2: the placeholder code](#7-login-part-2-the-placeholder-code) | reject placeholder input and tell the user where the real value lives |
| 8 | [8. Login, part 3: the field named like the grant type](#8-login-part-3-the-field-named-like-the-grant-type) | the field was named after the grant type: `authorization_code` |
| 9 | [9. The full root filesystem (cache location defaults)](#9-the-full-root-filesystem-cache-location-defaults) | a default that fills `/` is a bug, not a footgun |
| 10 | [10. The Ctrl-C fire drill](#10-the-ctrl-c-fire-drill) | atomic tmp+rename writes make an instant exit safe |
| 11 | [11. "Failed to open descriptor file" — quoting through the Wine boundary](#11-failed-to-open-descriptor-file--quoting-through-the-wine-boundary) | quotes are re-escaped crossing the Wine boundary — pass the path bare |
| 12 | [12. The email/password screen that wasn't a login failure](#12-the-emailpassword-screen-that-wasnt-a-login-failure) | an in-game login screen meant a missing entitlement, not a bad token |
| 13 | [13. Corrections and follow-ups](#13-corrections-and-follow-ups) | the ledger of what we got wrong, kept in the open |
| 14 | [14. Wine "unimplemented function" abort — the Proton build, not the prefix](#14-wine-unimplemented-function-abort--the-proton-build-not-the-prefix) | a Wine API you expect to exist aborting means that Proton build is broken — switch Proton, not prefix |
| — | [Validated results (for the record)](#validated-results-for-the-record) | the measured numbers, on the hardware this was built against |
| — | [Appendix: environment quirks that shaped the work](#appendix-environment-quirks-that-shaped-the-work) | the small, real gotchas that cost hours |

---

## 1. The launcher wouldn't run under Wine at all — pivot

**Symptom.** The official NeoLauncher is a Windows app; the obvious path is Wine.

**Diagnosis.** It's WinUI 3 / Windows App SDK. Those render through OS-provided
composition APIs that Wine doesn't implement. No amount of prefix tuning, winetricks,
or DLL overrides gets a WinUI3 app to show a window.

**Resolution.** Stop fighting it: everything the launcher *does* is HTTP + process
launch, which Python does natively. Reconstruct the protocol instead of emulating the
client. This decision defined the whole project.

**Lesson.** When the goal is "play the game on Linux," the launcher is a means, not an
end. Emulating a GUI is almost always harder than replacing the logic beneath it.

## 2. The chunk-URL guessing marathon

**Symptom.** We had the manifest and the CDN base URL, but chunk requests 404'd/403'd.
So: guess the URL scheme — 30+ candidates (ChunksV2–V5, guid-sharded dirs, hash-hex
and sha-named files, int vs hex manglings of every manifest field…). Every single one
failed.

**Diagnosis (of the guessing itself).**

- The CDN (Cloudflare R2) returns **403 to python-urllib's default User-Agent** — so a
  *correct* URL can look "blocked" and a wrong one just "not found". Two failure modes,
  one indistinguishable haze.
- R2 has **no bucket listing and no directory index** — nothing to probe against.
- Meanwhile the answer existed in plaintext 40 MB away: NeoFN ships Epic's
  `BuildPatchServices.dll` with the launcher, and the DLL contains the filename
  construction verbatim.

**Resolution.** Decompiled the DLL (the user uploaded it; toolchain below) and read
`FBuildPatchAppManifest.GetDataFilename`:

```
{ChunksV2|V3|V4}/{group:D2}/{rollingHash:X16}_{GUID}.chunk
subdir by manifest feature level; FL 13 → ChunksV3
group       = DataGroupList[guid]   (plain int, used raw)
rollingHash = ChunkHashList[guid] decoded to u64, %016X
GUID        = 32 uppercase hex
```

First constructed URL returned 200 and a SHA-1-perfect chunk.

**Lesson.** A 404 sweep across guessed URL shapes has nearly zero information content.
Before guessing, inventory what binaries sit on disk — the client almost always ships
the code that builds those URLs. And send a custom User-Agent from byte one so 403s
can't masquerade.

## 3. Manifest numerics: the fixed-width decimal "blob" trap

**Symptom.** Manifest values like `"105245229242240051122072"` and `"031"` parse as
integers fine — and then nothing matches anything.

**Diagnosis.** Epic JSON manifests encode binary fields as **fixed-width zero-padded
decimal strings, 3 digits per byte**. `int()`-ing them produces garbage that only
fails later, far from the parsing site. Worse, it's *inconsistent*: `ChunkHashList`
and `ChunkShaList` are blobs (24 digits → 8-byte LE u64; 60 digits → 20-byte SHA-1),
but `DataGroupList` and `ChunkFilesizeList` are plain integers. One parser must treat
neighboring fields differently.

**Resolution.** Blob-decode by width and only by width (24→u64 little-endian, 60→SHA-1
bytes), plain-int everything else — mirroring exactly which `Parse*FromJsonElement`
variant the DLL calls per field.

**Lesson.** When a format has one foot in binary and one in JSON, encode the
*distinction* explicitly in your parser, and validate a round-trip (re-derive a known
value, e.g. the rolling hash that appears in a URL) before building on it.

> See [§13](#13-corrections-and-follow-ups) — what shipped is slightly more permissive
> than this describes.

## 4. The 404 that wasn't (misdiagnosed our own bug as CDN flakiness)

The best bug of the project. **Symptom:** during the first end-to-end pipeline test,
one chunk "404'd". Re-requesting it by hand *worked*. The URL was byte-identical. In
one process, manual steps returned 200 while the library function "got a 404".

**Diagnosis.** Added a spy wrapper that logged every request the function made:

```
200  …ChunksV3/56/4595257B1597E264_D054….chunk     ← four 200s!
404  …ChunksV4/D0/D054….chunk                      ← fallback form, hard 404
RuntimeError: chunk …: HTTP 404
```

The 200s were being *thrown away*. The chunk header parser read `storedAs` and the
SHA-1 at byte offsets 32/33 — the real offsets are 40/41 (4+4+4+4+16+8 = 40; the GUID
is 16 bytes, easy to mis-tally). The resulting SHA mismatch raised inside the retry
loop's `except`, which slept, retried, eventually fell through to the fallback URL
form (ChunksV4, legitimately 404 for this manifest), and reported *that* error. The
last error hid the first.

**Resolution.** Fix the offsets; teach the retry loop to distinguish transport errors
from verification errors; never let a verification failure masquerade as an HTTP
status. (Also note: R2 *does* transiently 404 existing objects — but that's a
backoff-with-limits concern, not an explanation for consistent failure.)

**Lesson.** When a retry loop wraps a parse-and-verify, the surfaced error describes
the *last* attempt, not the *cause*. Log per-attempt results, and treat "the server
is wrong" as the hypothesis of last resort — the parser was the suspect all along.

## 5. Structural edit corrupted the script (duplicate tail)

**Symptom.** After inserting a function via a fuzzy-matched text edit, `argparse` ran
fine but the new subcommand's handler didn't exist; inspection showed the file's tail
(main dispatch + `__main__` block) existed twice.

**Cause.** The edit matched a slightly-wrong anchor and re-emitted a region, leaving
duplicated content that still parsed — Python happily defined everything twice.

**Resolution.** Truncate at the first legitimate `__main__` block; re-add the lost
handler; `py_compile` + `grep -c "def cmd_config"` as integrity checks afterward.

**Lesson.** Fuzzy edits on a 700-line script need the same paranoia as production
deploys: a syntax check proves parseability, not integrity. Anchor structural edits on
unique, exact strings.

## 6. Login, part 1: the case-sensitive route that returned 500

**Symptom.** `GET /account/api/oauth/challenge/discord?…` → HTTP 500
(`numericErrorCode 1012`, generic "Sorry an error occurred"). Same from the user's
browser and from the sandbox — so not IP/UA blocking. Looked exactly like the service
being broken.

**Diagnosis.** The decompiled caller: `account.LaunchSsoAsync("Discord", …)` — capital
D. The route is case-sensitive; unknown casing falls into a generic 500 instead of a
404, which is maximally misleading.

**Resolution.** `challenge/Discord` → clean 302 to `discord.com/oauth2/authorize…`.

**Lesson.** A generic 5xx can be a 404 in costume. When a URL "breaks the server",
diff your string against the client's literal — character by character, case included.

## 7. Login, part 2: the placeholder code

**Symptom.** Login callback fired (notification appeared!) but exchange failed with
`400 invalid_request`.

**Diagnosis.** The user had pasted the literal example `code=…` — the `…` was my
placeholder for "the long code". The error was real; the input was fictional.

**Resolution.** Reject placeholder/truncated codes (`…`, `...`, `CODE`, <16 chars)
with an explanatory message before hitting the network. UX hardening is part of
protocol correctness: a confusing error from a valid-shaped request sends you hunting
bugs that don't exist.

## 8. Login, part 3: the field named like the grant type

**Symptom.** A real code, correctly extracted from the callback URL, still got
`400 invalid_request` — and the error's `errorMessage` was the bare word
`authorization_code`.

**Diagnosis.** That errorMessage was not noise — it named the missing field. The
decompiled `OAuthTokenRequest` serializer builds the form as
`grant_type=authorization_code&authorization_code=<code>`. NeoFN's backend wants the
code in a field *named* `authorization_code`, not OAuth's standard `code`. With the
standard field the endpoint reports the request as malformed; with the right field and
a bogus value it returns a *different* error (`authorization_code_not_found`) —
validation had finally reached the value itself.

**Resolution.** Send `authorization_code`. Login succeeded: *"Logged in as
Agentpuggles"*.

**Lesson.** Read error payloads literally — they often name exactly what's missing.
And in interop work, the *shape* of the original client's serializer is the spec;
the standard is a suggestion. (Confirming a fix by how the *error class changes* is a
cheap, powerful probe when you can't succeed yet.)

## 9. The full root filesystem (cache location defaults)

**Symptom.** `install 10.40 -d /mnt/games/…` — target disk had 185 GB free — yet the
machine ran out of space at ~4.3 GiB, filling `/` to 100%.

**Diagnosis.** Chunks cache under `~/.local/share/neo/cache/` before assembly — i.e.,
on the root partition, which had only a few GB (ext4's 5% root reserve made `df`'s
"Avail" look even smaller). Install-target and cache are independent paths; the
default coupled the bulk cache to whatever disk `$HOME` lives on.

**Resolution.** `NEO_CACHE` env + `cache_dir` config; user moved the cache to the big
disk and resumed. The interrupted 4.3 GiB was retained (cache writes are atomic) and
the re-run picked it up. Documented peak-disk math: compressed build size (cache) +
full size (install) simultaneously, until post-success purge.

**Lesson.** Any component that writes gigabytes needs a configurable location from
day one, and defaults should assume the system disk is the *smallest* disk.

## 10. The Ctrl-C fire drill

**Symptom.** Interrupting an install dumped
`Exception ignored on threading shutdown … KeyboardInterrupt` stack noise.

**Diagnosis.** Pool worker threads were mid-request; interpreter shutdown tried to
join them; the second Ctrl-C interrupted the join. Purely cosmetic — all writes are
tmp+rename — but it *looks* like damage, and users will panic correctly.

**Resolution.** Handle the first KeyboardInterrupt with an immediate `os._exit(130)`
after a one-line "progress kept, re-run to resume" message. Safe precisely *because*
atomicity is a documented invariant of every write path.

**Lesson.** Design interruptibility in, then make the interrupt path itself clean.
The time to simplify Ctrl-C handling is before the first user hits it mid-62-GB.

## 11. "Failed to open descriptor file" — quoting through the Wine boundary

**Symptom.** Launch under umu/Proton: Proton initialized, ntsync up, the game process
ran — and exited in seconds with a dialog *"failed to open descriptor file smth smth"*.

**Diagnosis.** Two independent defects in how we built `-basedir`, both invisible on
Windows and lethal under Wine:

1. Our Windows path contained `Z:\\mnt` — a doubled backslash after the drive letter
   (a construction bug; nothing normalized it away).
2. The Windows launcher passes a quoted value (`-basedir="C:\…\Win64"`) because it
   builds one *raw command-line string*. We passed the quotes as part of an *argv
   element* through Python → umu → Wine, which rebuilds a Windows command line by
   quoting/escaping argv. The embedded quotes came out escaped (`\"`), UE4's
   old-style parser left the stray backslash attached to the path, and the engine
   resolved a mangled content root — hence a descriptor-file failure.

Evidence before fixing: the error string is not prism's. We pulled the **vanilla**
`FortniteClient-Win64-Shipping.exe` (124 MB) from the CDN through our own chunk engine
(SHA-1-verified, naturally) and grepped it — `Failed to open descriptor file %s` is
stock UE4, the project/plugin descriptor loader. That ruled out prism and pointed
straight at path resolution.

**Resolution.** Pass `-basedir` bare (the path had no spaces; the engine tokenizes on
whitespace, and NeoLauncher's own running-game detector regex accepts the bare form
too) and fix the backslash construction. Also map install paths inside the prefix's
`drive_c` to `C:\…` instead of `Z:\…` when applicable.

**Lesson.** Crossing the POSIX-argv → Windows-command-line boundary *re-encodes*
arguments: quotes, backslashes, and spaces all get rewritten. Never copy a raw
command-line string from a Windows client into an argv-based launcher verbatim —
re-derive each argument, and prefer forms that survive re-encoding (no embedded
quotes). And grep the binary that shows the error before blaming the one you can't
see.

## 12. The email/password screen that wasn't a login failure

**Symptom.** The game booted (fix #11 landed) — and presented the stock Epic
email/password screen. Everything before it worked; surely auth was broken?

**Diagnosis.** The game's own log (`FortniteGame.log`) told the real story in order:

```
Sending Login request. url=https://account-public-service-prod.ol.epicgames.com/…
Kill auth sessions … neofn.dev … code=204
Successfully logged in user. DisplayName=[Agentpuggles]        ← login WORKED
CheckPlatformPlayAllowed: play IS allowed
CheckEntitledToPlay → QueryAvailableFeature → 403:
  "Login is banned or does not posses the action 'PLAY' … for platform ''"
OnGrantFreeAccessComplete: Result: Succeeded                  ← auto-grant ran
(re-check 3s later: still forbidden)
AbortLoggingIn → ForceLogout → "You do not have permission to play Fortnite."
```

Authentication succeeded — including prism's URL redirection (requests aimed at Epic's
account host were served by neofn.dev; the kill-sessions call hit the right backend
with 204). The logout-and-fallback-to-login-screen is the game's standard reaction to
a failed *entitlement* check. And the entitlement was missing because, as the user
then clarified, NeoFN hadn't actually launched yet — the PLAY action simply isn't
granted while the service is pre-launch. (The auto-grant flow's "Succeeded" is the
request completing, not access being granted.)

**Resolution.** None required in the launcher — the command line is character-for-character
the Windows client's. Added visibility (`neo status` now surfaces `allowedActions` and
`fortniteAccess`) so the day the switch flips, it's observable from the terminal.

**Lesson.** A login screen is a *fallback UI*, not a diagnosis. Distinguish
authentication from authorization from entitlement in any gated system, and get the
game's state-machine log before touching working code. Also: sometimes the correct
conclusion is "not our bug" — and you should be able to *prove* it.

## 13. Corrections and follow-ups

Added when these notes were folded into the repository, so the record stays accurate
next to the code they describe.

- **`ChunkFilesizeList` is not treated as strictly plain-int.** Note 3 says blobs are
  decoded "by width and only by width" with everything else plain-int. What shipped is
  `neo.parse_num`, which accepts either form for `ChunkFilesizeList` and
  `FileChunkParts`: a digit string whose length is a multiple of three *and greater
  than three* decodes as a blob, anything else as a plain int. So a 3-digit
  `"031"` reads as `31` (correct for `DataGroupList`), while `"000001"` reads as
  `256`. The unguarded edge is a genuine plain int with 6, 9 or 12 digits —
  `parse_num("100000000")` returns `100`. Not observed in current manifests; recorded
  in [protocol.md §10](protocol.md#10-known-ambiguities).
- **`neo launch` could not forward extra UE4 arguments** — fixed in 0.4.0. The
  `extra` positional used `nargs="*"`, so argparse rejected flag-shaped tokens:
  `neo launch 10.40 -windowed` exited 2 with `unrecognized arguments: -windowed`.
  It is now `nargs=argparse.REMAINDER` (options must precede the UE4 arguments);
  the test that pinned the limitation (`TestKnownLimitations`) was rewritten to
  pin the fix (`TestLaunchArgumentForwarding`).
- **Note 5's own advice applies to this document.** The duplicate-tail corruption came
  from a fuzzy-matched edit on a 700-line script. These notes were added as whole new
  files rather than inserted into existing ones, and both were checked for duplicate
  headings, unbalanced fences and dangling links afterward.

## 14. Wine "unimplemented function" abort — the Proton build, not the prefix

**Symptom.** `neo launch` under umu/Proton: protonfixes and ntsync come up, then Wine
kills the process with `wine: Call from <addr> to unimplemented function <module>.<fn>,
aborting`, and the game exits 1 within seconds. The functions named are often absurd —
in the report that started this, `shell32.dll.SHGetFolderPathW` and
`win32u.NtGdiDdDDIQueryFSEBlock`, APIs Wine has shipped for years. No game window ever
appears, and the abort address is identical across runs.

**First diagnosis (wrong, and how we knew).** We treated it as a prefix/Proton mismatch
— the prefix built by one Proton, run by a self-updating `Proton … Latest`, so built-in
DLLs load from mixed generations. The fix we gave was "pin a Proton and recreate the
prefix." **It did not fix it**: rebuilding the prefix from scratch with the same Proton
reproduced the abort byte-for-byte (same call address). That disproved the prefix theory
— a stale-prefix failure dies after a fresh prefix; this one did not care about the
prefix at all.

**Diagnosis (what it actually is).** An "unimplemented function" abort on an API that
*is* implemented is the downstream symptom of Wine's own modules failing to initialise
out of a given Wine/Proton build — the `win32u`/`gdi32`/`user32`/`shell32` set inside
that Proton is inconsistent or broken at startup, before the game's own code runs. It is
deterministic *per Proton build*: switch to a different, known-good Proton lineage and it
boots cleanly with the same command line and the same prefix. The launcher's own
end-to-end validation (§8) had booted this exact command line on umu 1.4.3 /
Proton-CachyOS / ntsync; a later build of that same floating "Latest" Proton regressed —
the self-updating label is exactly why it is not a stable reference point.

**Resolution.** Use a different Proton, and make it the persistent default so launches
are reproducible:

```sh
neo config proton GE-Proton     # umu fetches & keeps the latest GE-Proton updated
neo launch
# or, one-off:
PROTONPATH=GE-Proton neo launch
# or pin an exact build so it stops moving under you:
neo config proton GE-Proton-9-27
```

umu selects the Proton from the **`PROTONPATH` environment variable**, not a CLI flag —
`neo launch --proton <p>` sets that for the child process, and the config `proton`
setting is applied when `--proton` is absent. (An earlier revision of the launcher
appended `--proton <p>` to the umu-run command line, which umu does not define and would
have misread as the game executable — fixed.)

`neo launch` now spots this signature on stderr (`to unimplemented function <m>.<f>,
aborting`) and prints the switch-Proton steps above instead of a bare `game exited: 1`.

**Lesson.** Two, one methodological. First: *verify a diagnosis before documenting it as
certain* — we shipped a plausible "recreate the prefix" fix that a single fresh-prefix
run falsified, and the correction is recorded here rather than papered over. Second: a
*built-in, shipped-for-years* Wine function reporting unimplemented means that Wine
build is internally broken at startup — change the Wine/Proton, don't chase the prefix.
And when a "Latest"/auto-updating component is part of the environment, it is not a
stable reference; a reproducible setup pins a version.

---

## Validated results (for the record)

| milestone | evidence |
|---|---|
| Manifest parse | 10.40: 411 files / 62,032 chunks; FL 13; all blob fields round-tripped |
| Chunk URL scheme | first constructed URL → 200, header GUID+rolling hash match URL |
| Chunk format | zlib inflate to 1 MiB, header SHA-1 == manifest `ChunkShaList` |
| Downloader | 96-chunk parallel test @ 55.8 MiB/s aggregate, 100% SHA-1 match; cross-file chunk dedup observed (2 files sharing 1 chunk) |
| Full install | 62,032 chunks / 27.9 GiB compressed → 61.9 GiB installed in 22m40s @ ~26 MiB/s single-client; 411/411 files verified at assembly; cache purge after |
| Resume | interrupted install re-run picks up cached chunks instantly |
| Auth | Discord SSO end-to-end on target hardware; session refresh; kill-others 204 |
| Launch | Proton boot → game window; in-game auto-login as the correct account; prism redirection confirmed from inside the game |
| Blocker | server-side PLAY entitlement (pre-launch), not launcher-side |

## Appendix: environment quirks that shaped the work

- **Decompilation toolchain** (memory-constrained sandbox): .NET SDK tarball +
  `ilspycmd` nupkg unzipped by hand (`dotnet tool install` bus-errored);
  `DOTNET_EnableWriteXorExecute=0` to coexist with the sandbox's W^X; toolchain lived in
  volatile `/tmp` and was rebuilt on demand — keep sources in the persistent workspace.
- **File transfer to the sandbox**: the user's DLLs came through litter.catbox.moe
  (1-hour TTL) — fine for one-shot artifacts, useless for anything you value.
- **R2 behaviors**: 403 on python-urllib UA; transient 404s on existing objects
  (retry with backoff, bounded); no listing/index anywhere on the bucket.
- **Never-released finds**: `EpicGames/BuildPatchServices` does not exist on GitHub
  (the DLL ships only inside clients); legendary/other tools' chunk-dir heuristics
  (ChunksV2–V5) were directionally right but the exact filename comes from the DLL.
