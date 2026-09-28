# Blue Diamond v2 preservation archive

This folder preserves the complete **published Blue Diamond v2 runtime package** selected in the owner's comma 3X photos: **Blue Diamond v2 (December 12, 2023)**, catalog key `NLP+BDv2`, generation `1`.

The archive branch is `backup/blue-diamond-v2-2026-09-28`. Its parent is the owner's exact pre-documentation `release-c3` commit, [`f4fbb5bc628da0f363e83c2b7c80e3793327eed3`](https://github.com/aeae1/openpilot/tree/f4fbb5bc628da0f363e83c2b7c80e3793327eed3). All files from that parent are preserved unchanged; this archive adds only this backup folder. The branch therefore also retains the associated prebuilt UI, model runners, vehicle code, NNLC files, and dependency/OS manifests that were tracked in the deployment repository.

## Contents

| File | Purpose | Bytes |
|---|---|---:|
| `supercombo-blue-diamond-v2.thneed` | Driving model | 49,235,840 |
| `navmodel_q_gen1.dlc` | Matching generation-1 navigation model | 3,630,942 |
| `supercombo_metadata_gen1.pkl` | Matching model output metadata | 727 |
| `upstream-models-v3.json` | Preserved upstream catalog, including original URLs and checksums | See file |
| `manifest.json` | Provenance, exact versions, file hashes, loader contract, and limitations | See file |
| `SHA256SUMS` | Checksums for the three payloads and preserved catalog | See file |

The three model payloads total **52,867,509 bytes: 52.87 MB / 50.42 MiB**. These are ordinary Git blobs containing the real bytes, not Git LFS pointers or links to external downloads. Their continued availability through this branch does not depend on the original GitLab download URLs remaining live.

## Provenance and verification

The catalog was retrieved from [`sunnypilot/sunnypilot-models`, commit `ea53605c39516336897b186ae76a22c74f6c658c`](https://github.com/sunnypilot/sunnypilot-models/blob/ea53605c39516336897b186ae76a22c74f6c658c/docs/models_v3.json). The three payloads were downloaded from the original GitLab URLs recorded there on September 28, 2026. Each SHA-256 matched its published catalog checksum exactly. The metadata pickle was preserved as bytes and was not deserialized during archival.

This verifies the **published package**. No files were read from the owner's comma, so this is not yet a byte-for-byte comparison against that device's installed copies. The displayed model name identifies the intended package; a future read-only device checksum comparison can establish the last link.

## Retrieve and verify on a computer

Use a separate directory on a computer. These commands retrieve the archive; they do not install software on a comma or change any driving settings.

```sh
git clone --depth 1 --single-branch --branch backup/blue-diamond-v2-2026-09-28 \
  https://github.com/aeae1/openpilot.git blue-diamond-backup
cd blue-diamond-backup/backups/blue-diamond-v2
sha256sum -c SHA256SUMS
```

Cloning retrieves the full preserved deployment tree as well as this model package. To download only the package, use GitHub's raw download links for the three payload files, `SHA256SUMS`, `manifest.json`, and `upstream-models-v3.json`. Keep them together. The `sha256sum` command is available on Linux; on macOS, use `shasum -a 256 -c SHA256SUMS`.

For a long-term record, retain the full archive commit ID returned by `git rev-parse HEAD`. A commit ID identifies the exact contents even if a branch name is moved later. Keeping an additional local copy is useful independently of GitHub.

## Compatibility and eventual restoration

The recorded setup uses a **comma 3X**, a **2025 Chrysler Pacifica Hybrid**, and the owner's **`0.9.6.1-release` / `release-c3`** deployment. `launch_env.sh` in that deployment requests **AGNOS 9.6**; the actual installed OS version was not read from the device. The OS download manifest is preserved in `system/hardware/tici/agnos.json`, but its partition images are not included in this model archive.

The archived `modeld.py` and `navmodeld.py` load custom models from `/data/media/0/models`. Their generation-1 loader contract is:

| Parameter | Expected value for this package |
|---|---|
| `CustomDrivingModel` | `1` |
| `DrivingModelGeneration` | `1` |
| `DrivingModelText` | `blue-diamond-v2` |
| `DrivingModelMetadataText` | `gen1` |
| `NavModelText` | `gen1` |

These values are derived from the source and upstream catalog. They are not an export of the owner's parameters, and do not document every UI selection/bookkeeping field. This archive contains no script that applies them.

A future clean-device restoration needs the compatible deployment, these three matching files, the selected model, and the owner's separately documented preferences. The replacement device needs its own registration/pairing and camera calibration. Automatic preference recovery remains a proposed feature, not something this backup implements. No replacement-device restoration has been tested.

**Use the original `release-c3` deployment identity when restoring.** This backup branch is a preservation container, not a newly tested install branch: the software has behavior that depends on its branch name. Also, the stock `selfdrive/modeld/models/supercombo.thneed` retained in the deployment is not the custom Blue Diamond file in this folder. Merely cloning the repository does not select or install Blue Diamond into `/data/media/0/models`.

## Scope

This is a complete backup of the catalog's Blue Diamond v2 runtime package and a preserved copy of the tracked deployment tree. It is **not** a full disk image, an export of device preferences, a fresh-install guarantee, or a model training checkpoint. It excludes device identity, private keys, pairing credentials, calibration/learned values, offline maps, recordings, and personal tokens. Upstream attribution and existing license notices remain applicable; this archive does not relicense the model artifacts.
