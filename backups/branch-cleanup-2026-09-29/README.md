# Branch cleanup record

I wanted the branch list to show the versions I actually use, without throwing away useful old work. This cleanup covers the 42 inactive branches listed in [manifest.json](manifest.json). Their last commits date from 2022 through April 2024. The audit found 29 histories that diverged from the current `master` and 13 separate histories, so none was treated as redundant merely because it was old.

## Retained branches

| Branch | Why it stays |
|---|---|
| `pacifica` | My replacement-device installation with the saved profile and bundled Blue Diamond files |
| `release-c3` | The original deployment branch used by my current comma |
| `backup/blue-diamond-v2-2026-09-28` | The verified Blue Diamond archive and original deployment snapshot |
| `master` | The repository's default branch and a different historical source tree worth preserving |

The manifest records every original branch name, exact commit, tree, intended archive tag, and comparison result. The archive prefix is **`archive/cleanup-2026-09-29/`**. These are lightweight Git tags pointing to the original commits. They keep the original tracked files and Git history reachable while allowing the obsolete branch names to disappear from the normal branch list. This is organization, not a purge of repository history or a promise of reduced storage usage. Existing release tags are retained.

The cleanup requires all 42 archive tags to be created and read back successfully before any branch deletion. It rechecks the branch inventory, open pull requests, protected status, and expected commits. Deletion uses one atomic Git push with an explicit expected commit for every branch, so a changed candidate makes the deletion fail instead of removing somebody's new work. A temporary GitHub Actions job performed the operation. Its workflow, script, and tests were removed after verification, leaving this record and the manifest.

## Files and other cars

No existing deployment files were deleted. The audit of the `pacifica` tree found no obvious tracked scratch files, backup copies, or rejected patches. It retained all vehicle interfaces, controllers, fingerprints, CAN definitions, panda files, NNLC models, driving/monitoring/navigation models, compiled programs, shared libraries, translations, tests, tools, and license notices. Several of these are selected dynamically, so an ordinary text search alone cannot establish that they are unused.

The frozen deployment's original bundled driving model is retained too. Blue Diamond being selected does not make that fallback disposable. Vehicle-specific experimental branches are archived with their exact original commits instead of having their contents discarded.

Keeping support files does not make the saved Pacifica profile appropriate for a different vehicle. That profile includes a Pacifica vehicle selection and mount-specific offsets. A different car needs its own compatible vehicle setup; use the original `release-c3` path or deliberately configure the appropriate vehicle rather than assuming the Pacifica defaults transfer.

## If future me wants an old branch back

Find the branch in `manifest.json`, open its archive tag on GitHub, and create a new branch at that tag using the original branch name. A tag identifies the preserved version; it is not a new installation branch. For example, the old `ceed-long` branch is preserved by `archive/cleanup-2026-09-29/ceed-long`.

The Blue Diamond archive's pinned commit remains `70f4db9d01be4ceb3706c508484055f615e0fa0a`. This cleanup does not change its files, either deployment branch, or the physical comma device.

## Execution status

Completed through [GitHub Actions run 36519301122](https://github.com/aeae1/openpilot/actions/runs/36519301122), using cleanup commit `7c2d23b7b5be2f3eb820930c82162b76c45b29da`. The 10 guard tests passed before the live operation. All 42 archive tags were verified against the original tips, the 42 obsolete branches were removed, and the four retained branches were checked again. The pre-existing release tags were preserved.

The deployment/archive heads remained exactly:

- `pacifica`: `9afa1e6b0bf819993849bd19f0c2b55a0f2cac1c`
- `release-c3`: `c5903de158dd7707128b30cbaaccdde3a3b6b462`
- `backup/blue-diamond-v2-2026-09-28`: `70f4db9d01be4ceb3706c508484055f615e0fa0a`

`master` received only the cleanup record and this README documentation after the temporary job was removed. No current-device access or software installation was performed.
