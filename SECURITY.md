# Security policy

`neo` is an unofficial launcher that holds a real account session, writes files driven
by a remote manifest, and execs a game binary. Those are the three things this policy
is about.

## Reporting a vulnerability

**Please use a private report, not a public issue.**

1. Open a
   [private vulnerability report](https://github.com/Agentpuggles/Neo-Linux/security/advisories/new),
   or email the maintainer directly if the repository does not expose the advisory form.
2. Include: the affected version (`neo --version`), the command you ran, and what the
   attack would be — "a hostile CDN response can write outside the install directory"
   is actionable; "HTTP is unsafe" is not.
3. A reproducible proof of concept is welcome, but strip anything that could expose an
   account: no real access/refresh tokens, no full `auth.json`, no exchange codes.

Expect an acknowledgement within a week and a first assessment within two. Fixes land in
a normal release; the advisory and a `CHANGELOG.md` entry are published once a fix is
available, since a description of the hole is itself exploitable until then.

## What is in scope

| Area | Why it matters |
| --- | --- |
| Writing outside the install directory | File names and symlink targets come from a downloaded manifest. `install_path()` is the guard; a bypass of it is a bug. |
| Hash verification | Chunk SHA-1, file SHA-1 and prism SHA-256 are what stand between a tampered CDN and arbitrary code running as you. Any way to assemble a file the manifest did not authenticate is a bug. |
| Session storage | `auth.json` must stay `0600`, and tokens must never land in logs, in the argv of a long-lived process, or in an error message. |
| Exchange codes | They authenticate the game to the account service and expire on purpose. Printing them, persisting them, or reusing them across launches is a bug. |
| Command construction | `launch` builds the `umu-run` command line. Anything that lets manifest- or config-derived text inject an argument beyond `-basedir` and the extra UE4 options is a bug. |
| Cache and state parsing | `state.json`, `.neo-manifest.json` and the chunk cache are read back with trust; malformed input must fail loudly — never through `eval` or `pickle`. |

## Explicitly out of scope

- **The OAuth client id and secret in the source.** They are the official Windows
  launcher's public client credentials, reproduced for interoperability (the same
  approach [legendary](https://github.com/derrod/legendary) takes). They authenticate
  *the application*, not any user account, and cannot be rotated by us.
- **Anything NeoFN's services do with your account.** Bans, entitlement revocation and
  service-side changes are not this project's security defects — using an unofficial
  launcher is itself a judgement call each user makes.
- **Attacks that already require your session file, your home directory, or code
  running as you.** At that point the confidentiality boundary is your user account.
- **Weaknesses in umu-launcher, Proton, Wine or the game binary.** Report those
  upstream; [README → Acknowledgements](README.md#acknowledgements) links the projects.

## Handling rules this project follows

- Downloads are verified before they are used, and every write is `tmp` + atomic rename,
  so a failed or interrupted run cannot leave a half-trusted file behind.
- Manifest-supplied paths are confined to the install directory.
- `auth.json` is written `0600`; `neo logout` empties it rather than deleting it, so the
  mode bits and any symlink you set up are preserved.
- Secrets are masked in the printed launch command line (`-AUTH_PASSWORD=***`,
  `-p=***`), and `--dry-run` prints the same masked form.
- No telemetry, no update checker, nothing that phones home beyond the launcher's own
  API calls.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.6.x` | ✅ |
| `< 0.6` | ⚠️ best effort — please reproduce on `0.6.x` first |

After updating for a session-handling issue, re-login (`neo logout && neo login`): a
stolen refresh token stays valid until the account service revokes it, and rotating it
is the one mitigation the launcher cannot do for you.
