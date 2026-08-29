## What this changes

<!-- One paragraph: the behaviour a user or a maintainer will notice. -->

## Why

<!-- Link the issue (`Closes #123`) or explain the failure this removes. If a wire-format
     detail motivated it, say which service/endpoint — that is the part that goes stale. -->

## How it was verified

- [ ] `make check` passes (ruff, the offline suite, CLI smoke)
- [ ] New/changed behaviour has a test in `tests/` (or a reason why not)
- [ ] `docs/protocol.md` updated if any request, encoding or command line changed
- [ ] `docs/engineering-notes.md` has an entry if this cost real debugging time
- [ ] `CHANGELOG.md` has a line under `## [Unreleased]`
- [ ] README usage/configuration tables still describe the flags as they behave

<details>
<summary>On-hardware checks (only needed for install, verify, launch or cache changes)</summary>

```sh
neo install <version> && neo verify && neo launch --dry-run
```

- [ ] Install completed and reported the same file count as the manifest
- [ ] `neo verify` clean afterwards
- [ ] `neo launch --dry-run` prints the expected command line (paste it, tokens masked)
- [ ] Interrupted mid-download with Ctrl-C, then resumed with the same command

</details>

## Notes for the reviewer

<!-- Anything surprising: an intentional simplification, a compatibility concession, a
     follow-up you deliberately left out. Disk-format changes need a migration note here. -->
