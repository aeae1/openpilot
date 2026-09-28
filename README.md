# aeae1pilot — a personal sunnypilot setup

This repository preserves a personal sunnypilot setup used with a **2025 Chrysler Pacifica Hybrid and a comma 3X**. The owner likes its current driving behavior: **Blue Diamond v2**, a **Laneful** profile, **NNLC**, and a side-mounted camera using the legacy **−20 cm camera offset**. Preserving that behavior is the project's priority.

The active personal deployment is **[`release-c3`](https://github.com/aeae1/openpilot/tree/release-c3)**. GitHub's default branch, `master`, is a different historical source tree. **This README documents `release-c3`, including when viewed on `master`; do not assume the surrounding code on `master` implements these personal changes.**

This documentation was audited on **September 28, 2026**, using the final code diff, commit history, and the owner's settings photos. It describes the resulting code, including changes that the former short README omitted. It does not imply a new hardware test or an export of the device's complete state.

## Versions and preserved baseline

| Item | Recorded value |
|---|---|
| Personal deployment branch | `release-c3` |
| Software version | `0.9.6.1-release` |
| Last driving-code commit before this documentation | [`f4fbb5bc628da0f363e83c2b7c80e3793327eed3`](https://github.com/aeae1/openpilot/tree/f4fbb5bc628da0f363e83c2b7c80e3793327eed3), August 13, 2025 |
| sunnypilot release baseline for the personal diff | [`e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8`](https://github.com/aeae1/openpilot/tree/e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8), `sunnypilot v0.9.6.1`, February 28, 2024 |
| Selected driving model shown in photos | **Blue Diamond v2 (December 12, 2023)**, `NLP+BDv2`, generation 1 |
| OS version requested by this deployment's `launch_env.sh` | **AGNOS 9.6**; the device's installed OS was not independently read |
| Vehicle used by the owner | **2025 Chrysler Pacifica Hybrid** |
| Historical vehicle label displayed by this build | `Chrysler Pacifica Hybrid 2019–23` |
| Hardware | **comma 3X** |
| Default `master` branch before this documentation | `c53c90f7fac73a9ba7dad81bf9c349535651bf6d`, May 8, 2024, version `0.9.7.0`; not the personal deployment |

The software, model, and personal edits have different dates. A 2025 commit does not make the underlying release or selected driving model a 2025 version. The old vehicle label is retained from the platform definition; it is not a claim that this fork has a separately validated 2025 vehicle port.

The deployment includes `prebuilt`, a compiled `selfdrive/ui/ui`, compiled model runners, and other release binaries. Much of the matching C++ UI source is absent. Editing the unrelated `master` tree is not a reliable way to rebuild this exact UI.

## Blue Diamond v2 backup

The **[Blue Diamond v2 archive](https://github.com/aeae1/openpilot/tree/backup/blue-diamond-v2-2026-09-28/backups/blue-diamond-v2)** preserves the complete three-file runtime package, its original catalog, SHA-256 checksums, and a compatibility manifest.

The exact archive commit is [`70f4db9d01be4ceb3706c508484055f615e0fa0a`](https://github.com/aeae1/openpilot/tree/70f4db9d01be4ceb3706c508484055f615e0fa0a/backups/blue-diamond-v2).

| Payload | Size |
|---|---:|
| `supercombo-blue-diamond-v2.thneed` | 49,235,840 bytes |
| `navmodel_q_gen1.dlc` | 3,630,942 bytes |
| `supercombo_metadata_gen1.pkl` | 727 bytes |
| **Total model package** | **52,867,509 bytes — 52.87 MB / 50.42 MiB** |

The archive branch descends directly from `f4fbb5b` and preserves its tracked files unchanged, adding only the backup folder. This retains the deployment's code and prebuilt dependencies as well as the custom model package. The model payloads are real Git blobs, not external-download links or LFS pointers.

All three downloaded payloads matched sunnypilot's published SHA-256 checksums. This establishes a verified copy of the published Blue Diamond v2 package. **The installed files on the owner's comma have not been read or hash-compared.** The archive is not a device disk image or model training checkpoint. See its README and `manifest.json` for verification and restoration boundaries.

## Personal code modifications

The authoritative comparison is [`e8de7d3…f4fbb5b`](https://github.com/aeae1/openpilot/compare/e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8...f4fbb5bc628da0f363e83c2b7c80e3793327eed3). Before the documentation update, the final net diff affected five runtime Python files and the README. Earlier experiments that were subsequently reverted are not additional active features.

### 1. Cruise-speed ceiling and button increments

In [`selfdrive/controls/lib/drive_helpers.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/lib/drive_helpers.py):

- `V_CRUISE_MAX` is **161 km/h**, raised from 145 km/h. That is approximately **100 mph**, not an unlimited cruise speed. This is the software setpoint ceiling; it does not prove that factory ACC accepts every requested speed.
- Imperial increments use the exact `CV.MPH_TO_KPH` conversion, **1.609344**, instead of 1.6.
- Small adjustments are **1 mph**; large adjustments are **5 mph**. Metric adjustments remain 1 km/h and 10 km/h.
- Large adjustments snap toward the next interval boundary when off-grid. An interval-relative tolerance handles values already near a boundary. This is the final implementation of the owner's “85 → 89 / 94” correction.
- With the owner's **ACC Long Press Reverse ON**, a short press requests the large adjustment and a long press requests the small adjustment.
- Speed changes are ignored in Park, Reverse, and Neutral. The code also ignores an adjustment below 0.5 m/s when the setpoint is unset, preserves the setpoint when resuming from cruise standstill, and avoids treating a button press that enabled cruise as another adjustment.
- The existing gas-override lower bound and final min/max clipping remain.

These modifications are in the non-PCM-speed helper. The inherited **Custom Stock Longitudinal** feature sets `pcmCruiseSpeed=False` on this supported Chrysler configuration, which makes this helper relevant even though the vehicle still uses factory ACC for longitudinal actuation.

### 2. MADS persistence and lateral eligibility

In [`selfdrive/car/interfaces.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/car/interfaces.py):

- `get_sp_started_mads()` returns the current `CS.madsEnabled` state instead of the old forward-gear/one-second rearming sequence.
- When cruise availability transitions from available to unavailable, the method clears its initialization flags and returns `False`.
- `get_sp_common_state()` no longer uses the original gear, open-door, and seatbelt checks to set `gear_allowed=False`. It assigns **`cs_out.latActive=True`** instead.

The owner's goal was to keep the chosen MADS state through parking and related interruptions. **The implementation changes lateral eligibility as well as retaining the selection.** Describing it solely as “remember the toggle” would be incomplete. These edits are in the shared interface, not a Chrysler-only wrapper.

This assignment does not mean steering is physically active at every speed or in every situation. `controlsd.py` still combines it with MADS state, minimum speed/standstill, brake behavior, steering faults, calibration, and other conditions. The Chrysler controller and panda also have their own constraints.

### 3. Door, seatbelt, stability-control, and high-speed events

In [`selfdrive/controls/lib/events.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/lib/events.py):

| Event | Personal change | What remains in that event definition |
|---|---|---|
| `doorOpen` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `seatbeltNotLatched` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `espDisabled` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `speedTooHigh` | `WARNING` and `NO_ENTRY` entries commented out | Neither of those entries is active |

The former README's “no warnings about seatbelt/door” was too broad: the no-entry definitions remain. These are changes to event handling, including disengagement/entry behavior, rather than just a quieter visual theme. The high-speed event change does not alter the model's training or demonstrate reliable performance at a higher speed.

### 4. NNLC loaded-notification suppression

In [`selfdrive/controls/controlsd.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/controlsd.py), `self.nn_alert_shown` starts as `True`, suppressing the periodic NNLC-loaded notification path. This does not create or force a successful NNLC model load. Absence of that notification is not evidence of which model is running.

### 5. Fork-origin recognition

In [`system/version.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/system/version.py), `github.com/aeae1/openpilot` was added to `is_comma_remote()`'s recognized-origin list. This changes the code's classification of the remote. It does not make the fork an official comma/sunnypilot build or certify that it was tested.

### Scope of the final changes

The final personal diff has **no net changes to the Chrysler-specific controller/interface/CAN files, panda safety files, or driver-monitoring code** relative to the stated sunnypilot baseline. Historical Chrysler experiments were reverted. This does not negate the shared-interface and event-handling changes described above, and it is not a safety-equivalence claim.

This is a personal fork with explicit behavioral departures from its upstream release. Other users should evaluate the actual code and their own hardware rather than treat the owner's satisfaction as general vehicle validation. Normal driver supervision remains necessary.

## Inherited features that shape this setup

The following are sunnypilot features configured by the owner, rather than newly written personal modifications:

- **MADS:** independent management of lateral assistance and ACC, with Cruise Main and brake behavior options.
- **Dynamic Lane Profile and custom offsets:** the legacy lane planner and its configurable camera/path biases.
- **NNLC / `NNFF`:** neural-network feedforward in torque lateral control. The enabled NNLC setting can select torque tuning even with “Enforce Torque Lateral Control” off. Exact NNLC model matching depends on the vehicle and EPS firmware; the loaded model filename has not been read from this device.
- **Custom Stock Longitudinal:** manages the requested cruise speed through the vehicle's stock ACC interface. The Pacifica's factory system still performs the longitudinal actuation; this is not full openpilot longitudinal control.
- **Vision-based turn speed control, nudgeless lane-change options, road-edge blocking, Quiet Drive, map/display options, and reverse driver-camera view.**

Blue Diamond v2 is the **driving model**, while the NNLC files are separate **steering-control models**. Backing up one does not identify which specific NNLC model was selected at runtime; the preserved deployment includes its available NNLC files.

### Why the offset and model combination matters

The selected profile is **Laneful**, with **Custom Offsets ON**, **Camera Offset −20 cm**, and **Path Offset 0 cm**. In this release, camera offset is read as an integer number of centimeters and applied to the predicted lane-line coordinates. Path offset is applied to the model path before blending. Lane confidence and width still affect how strongly the planner follows the lane-derived path.

The UI describes a decreasing camera-offset value as biasing the car farther left. This is the legacy lane-planner adjustment used by this setup. It is not a universal mounting calibration, and a newer setting with the same name may use a different implementation, sign convention, or model path. Do not transfer the numerical value between generations without checking the code.

## Owner's photographed preferences

**These are observed preferences, not programmed installation defaults.** They describe the owner's photos supplied for this review, not a complete parameter export. The tables omit device identifiers, local network details, account credentials, and unrelated car-brand toggles.

### Driving and lane behavior

| Setting | Observed value |
|---|---|
| Driving model | Blue Diamond v2 |
| Dynamic Lane Profile | Laneful |
| Custom Offsets | On |
| Camera Offset — Laneful Only | −20 cm |
| Path Offset | 0 cm |
| MADS | On |
| Toggle MADS with Cruise Main | On |
| Enable ACC+MADS with RES+/SET− | Off |
| Steering Mode After Braking | “Remain Active” appears selected; dimmed photo, parameter export needed for definitive confirmation |
| Disengage on accelerator | Off |
| NNLC | On |
| Enforce Torque Lateral Control | Off |
| Custom Stock Longitudinal | On |
| Experimental Mode | Off |
| Dynamic Experimental Control | Off |
| Vision-based Turn Speed Control | On |
| Speed Limit Control | Off |
| ACC Long Press Reverse | On |
| Auto Lane Change Timer | Nudgeless |
| Pause lateral below speed with blinker | Off |
| Delay automatic lane change with blind spot | Off |
| Block lane change at road edge | On |
| Units | Imperial / mph |

### Alerts, monitoring, and recording

| Setting | Observed value |
|---|---|
| Quiet Drive | On |
| Green traffic light chime | Off |
| Lead departure alert | Off |
| Hands-on-wheel monitoring option | Off; this does not disable camera-based driver monitoring |
| Lane departure warning | Off |
| Record/upload driver camera | Off |
| Disable onroad uploads | Off; this double-negative option does not disable onroad uploads |
| Screen recorder | Off |

### Display and maps

| Setting | Observed value |
|---|---|
| Developer UI / detailed metrics | Off |
| Feature status | Off |
| Display braking | Off |
| Standstill timer | Off |
| OSM debug | Off |
| End-to-end longitudinal status | Off |
| Sidebar temperature | Off |
| Onroad settings | On |
| Display driver camera in reverse | On |
| True speed display | Off |
| Hide speedometer | Off |
| Metrics above chevron | Speed; the menu labels this as applicable only to openpilot longitudinal control |
| Driving screen-off timer | Always On |
| Brightness | Auto |
| Maximum time offroad | 3 hours |
| Navigation full screen | Off |
| Map on left | Off |
| Map 3D buildings | Off |
| ETA in 24-hour format | Off |
| Mapd version shown | 1.8.0 |
| OSM database date shown | March 22, 2025, 14:03:37 |
| OSM region selection | United States / All States, approximately 4.8 GB listed |

The map screen's “Calculating…” size display does not prove every selected map file was downloaded. Neither the offline map files nor a private navigation token are included in the model backup.

## Defaults and replacement-device recovery

The current `selfdrive/manager/manager.py` seeds its existing defaults only when a parameter is absent. It does **not** currently seed the owner's full profile. Examples of differences are:

| Preference | Current code default | Owner's observed selection |
|---|---|---|
| `AccMadsCombo` | `1` / On | `0` / Off |
| `DynamicLaneProfile` | `1` / Laneless | `0` / Laneful |
| `CustomOffsets` | `0` / Off | `1` / On |
| `CameraOffset` | `4` / +4 cm | `-20` / −20 cm |
| `NNFF` | `0` / Off | `1` / On |
| `TurnVisionControl` | `0` / Off | `1` / On |
| `ReverseAccChange` | `0` / Off | `1` / On |
| `AutoLaneChangeTimer` | `0` | Nudgeless, corresponding to `1` in this release |
| `AutoLaneChangeBsmDelay` | `1` / On | `0` / Off |
| `ScreenRecorder` | `1` / On | `0` / Off |
| `ShowDebugUI` | `1` / On | `0` / Off |
| `FeatureStatus` | `1` / On | `0` / Off |

A fresh clone alone therefore does not reproduce the owner's setup. The custom driving-model files normally live outside the Git checkout at `/data/media/0/models`; model selection and most preferences live in the device's parameter store.

The agreed **future design**, still unimplemented, is to apply a named personal profile on a clean installation, preserve later manual adjustments during ordinary boots, and offer an explicit “Restore My Setup” action to reapply it. A replacement used comma is assumed to be wiped first. Device identity, registration, credentials, calibration, and learned values should belong to that replacement device rather than be blindly copied from the old one.

For an eventual restoration, preserve the exact deployment identity, obtain the matching three model files and verify their checksums, confirm model selection, reapply the documented preferences, and complete the replacement device's own setup/calibration. The archive README records the loader's required parameters. **No automatic restore procedure or clean-device installation has been implemented or tested as part of this documentation/backup work.**

## Lead marker and speed-display idea

A calmer lead marker with one readable speed value was discussed, but is **not implemented**. The owner's requirement is a trustworthy measured speed, not a smoothed estimate that merely looks precise.

In this branch, `selfdrive/car/chrysler/interface.py` sets **`radarUnavailable=True`**. This means the openpilot lead-processing path does not receive usable radar tracks through this port; it does not mean the Pacifica lacks radar or that its factory ACC stops using radar. The vision fallback derives lead speed from the driving model and ego-speed information. Smoothing its marker or rounding its digits would improve appearance without establishing measurement accuracy. This feature remains paused unless a reliable source can be demonstrated.

## Maintenance notes

- Compare against the pinned baseline when auditing personal modifications. Commit messages include experiments and reversions, so counting historical edits overstates the final changes.
- Keep the model/metadata/navigation-model combination together. The stock bundled `supercombo.thneed` is not the custom Blue Diamond v2 file.
- Recover the source matching the prebuilt release before attempting UI changes. The default branch is not a substitute for that investigation.
- Preserve the distinction between a named branch and a commit. This release contains branch-name-dependent behavior; an archive branch should not be assumed to behave identically if installed under its archive name.
- Preserve working behavior when evaluating later models or controls. Model generations, lane planning, offsets, and UI implementations are coupled; a model swap is not automatically a drop-in upgrade.
- The September 2026 work adds documentation and a model archive only. It does not change runtime code, seed preferences, install an update on a device, or add the proposed lead-speed UI.

## Attribution and license

This fork builds on [sunnypilot](https://github.com/sunnypilot/sunnypilot), [comma's openpilot](https://github.com/commaai/openpilot), and their contributors, including the authors of the inherited NNLC, mapping, vehicle-support, and UI features. Personal changes are maintained by **aeae1**. Much of the original work involved both AI assistance and manual editing; this README records the final code behavior rather than assigning authorship to individual edits.

The repository's existing [LICENSE](LICENSE) and third-party notices remain unchanged. Model provenance is recorded in the backup manifest, and archiving the artifacts does not relicense them. Historical upstream information remains in `CHANGELOGS.md` and `RELEASES.md`; those files describe upstream releases and should not be read as a list of personal modifications.
