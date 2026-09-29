# Pacifica first-install setup

This is my saved 2025 Pacifica Hybrid / comma 3X setup for the frozen 0.9.6.1 build. I like its existing Blue Diamond behavior. This folder makes the model and preferences available during a clean installation; it does not upgrade the driving model or the steering controller.

Use the installation links near the top of the [main README](../README.md). The automatic hook only runs on the `pacifica` branch on the device. Existing installations opt out, including ones without a profile journal. My current `release-c3` installation is unaffected.

## Contents and provenance

- `profile.json`: 82 explicit preferences and the six model-selection parameters. Values come from the owner's targeted device export of September 28, 2026. Its 18 absent off/zero settings are normalized to the string `0`; the raw export is not installed wholesale.
- `models/`: the complete published Blue Diamond v2 runtime package, generation 1. All three files were hash-matched against the actual device and the pinned GitHub archive.
- No device/account identifiers, tokens, private keys, calibration, learned values, routes, map files, or AGNOS partition images are included.

The original catalog entry is **NLP+BDv2**, Blue Diamond v2 (December 12, 2023). Provenance, the original catalog, and checksums are preserved in the [archive at 70f4db9](https://github.com/aeae1/openpilot/tree/70f4db9d01be4ceb3706c508484055f615e0fa0a/backups/blue-diamond-v2). This copy does not change upstream attribution or licensing. The repository's LICENSE and third-party notices continue to apply as originally provided; no new license is asserted for the model artifacts.

| File | Bytes | SHA-256 |
|---|---:|---|
| `supercombo-blue-diamond-v2.thneed` | 49,235,840 | `b298caa4be035dbe25b9158f0ba3d0b59a99e6a695a11fccda98b69f5050f29f` |
| `navmodel_q_gen1.dlc` | 3,630,942 | `c808717d073a0bb347f9ba929953c0b2b792ce9997f343f7e44a0b2b0e139132` |
| `supercombo_metadata_gen1.pkl` | 727 | `1924d0918e1cd5914598be67077aa99413eb346291b6b617fb83c222ea8991b8` |

## Startup behavior

`selfdrive/manager/manager.py` detects existing-install evidence before parameter cleanup, then calls `pacifica_setup.initialize()` before the inherited default loop, registration, and process preparation. Existing preference files count as evidence even when they are empty. Version/Git/calibration/learned-state markers and accepted terms/training also prevent automatic initialization. OS-created networking/identity values and the prebuilt mapd version do not by themselves prevent a clean install.

The helper keeps a journal at `/data/pacifica_setup/state.json`. It is deliberately outside Params so this prebuilt release needs no native registry or UI changes. New installs and explicitly requested restores verify every bundle file and native parameter key, mark the transaction pending, install and verify each file, write/read back preferences and selection keys, and finally mark complete. Blocking Params writes use the existing native atomic-write interface; the helper also syncs its files and directories.

An interrupted pending transaction resumes on the next startup. A different profile digest during that transaction is an error, not permission to mix versions. A completed transaction is a no-op on future boots, even if the user changes settings, selects another model, removes a preference, or a later profile is published. A missing journal alone never triggers replacement of existing settings. Do not delete the journal to force defaults.

Normal installation needs no manual model download. The user can request an explicit restore using the offroad-only command documented in the main README. That queues a reboot-time operation; it does not apply preferences while driving processes run. The UI was not rebuilt and has no new restore button.

`pacifica` has the same branch classifications as `release-c3`: sunnypilot release true, tested-branch bookkeeping true, stock comma release false, display category release. This preserves the existing feature gates and startup alert. The wording does not mean upstream maintainers tested this branch.

## Verification

From the repository root, these checks use only Python's standard library and do not require a device:

```sh
python3 tools/pacifica_setup.py --verify-bundle
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s selfdrive/manager/test -p test_pacifica_setup.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -O -m unittest discover -s selfdrive/manager/test -p test_pacifica_setup.py -q
```

The tests cover the actual payload checksums and captured critical settings; preservation of existing preferences, identity, calibration, and other models; complete/no-marker behavior; disk-full and corrupted-copy failures; unsupported parameters and silent write failures; interrupted installation at all 88 parameter-write positions and after each model rename; failure to commit the completion marker; resuming in another interpreter after an abrupt process exit; explicit restore gating; profile/journal validation; manager startup ordering; and branch classification. The native Params interface is represented by a filesystem adapter in these software tests. Runtime setup checks the real compiled key registry and reads back real Params writes on the device.

The GitHub Actions workflow runs the suite on Python 3.8 and 3.12, both normally and with optimization enabled. A workflow definition is not itself evidence that a particular run passed; check its actual result.

These checks do **not** execute the ARM model runners, replay vehicle data, or perform a physical comma 3X installation/OS transition. No new hardware driving test was performed. The baseline compiled UI, model runners, vehicle/controller code, and panda files are retained. Installer-service responses and the old AGNOS download URLs could not be fetched from the development workspace, so live external availability is not asserted. The initial install still needs Internet access for GitHub, the installer service, any OS download, and normal device registration. Only the Blue Diamond package's old external model host is removed from this installation path.
