# aeae1pilot: my sunnypilot setup

This is my personal sunnypilot fork for my **2025 Chrysler Pacifica Hybrid and comma 3X**. I'm really happy with how it drives. I'm running **Blue Diamond v2**, a **Laneful** profile, and **NNLC**, with my camera mounted off to the side and the legacy **camera offset set to −20 cm**. I like the camera there, and I like the behavior I've ended up with.

The setup is pretty much frozen in time, and I'm fine with that. I'm curious whether newer driving models might feel a little nicer, but I don't feel a need to upgrade just for a newer version number. My priority is to preserve what I already like and make any future changes deliberately.

**The branch I actually use is [`release-c3`](https://github.com/aeae1/openpilot/tree/release-c3).** GitHub's default branch, `master`, is a different historical source tree. This README describes `release-c3` even when you're reading it on `master`; the surrounding code on `master` doesn't contain the same personal changes.

I made the original changes with a mix of AI help and manual work, with plenty of edits and reversions along the way. This README is here so future me and anyone else looking through the repo can work out what's actually in it. It was checked against the final code diff and commit history. That was a documentation review, not a new hardware test or a full export of my comma.

## What I'm running

| Item | Recorded value |
|---|---|
| Branch I use | `release-c3` |
| Software version | `0.9.6.1-release` |
| Last driving-code commit before this documentation | [`f4fbb5bc628da0f363e83c2b7c80e3793327eed3`](https://github.com/aeae1/openpilot/tree/f4fbb5bc628da0f363e83c2b7c80e3793327eed3), August 13, 2025 |
| sunnypilot release baseline for the personal diff | [`e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8`](https://github.com/aeae1/openpilot/tree/e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8), `sunnypilot v0.9.6.1`, February 28, 2024 |
| Selected driving model | **Blue Diamond v2 (December 12, 2023)**, `NLP+BDv2`, generation 1 |
| OS version requested by this deployment's `launch_env.sh` | **AGNOS 9.6**; the device's installed OS was not independently read |
| My vehicle | **2025 Chrysler Pacifica Hybrid** |
| Historical vehicle label displayed by this build | `Chrysler Pacifica Hybrid 2019–23` |
| Hardware | **comma 3X** |
| Default `master` branch before this documentation | `c53c90f7fac73a9ba7dad81bf9c349535651bf6d`, May 8, 2024, version `0.9.7.0`; not the personal deployment |

There are a few different ages here: the driving model is from 2023, the sunnypilot baseline is from 2024, and my last driving-code edits were in 2025. The old `2019–23` vehicle label comes from the platform definition. I'm using this with my 2025 Pacifica, but that doesn't amount to a separately validated 2025 vehicle port.

This is a prebuilt release: it includes `prebuilt`, a compiled `selfdrive/ui/ui`, compiled model runners, and other release binaries. Much of the matching C++ UI source isn't here. If I want to change the UI later, I'll need to recover the matching source; grabbing the unrelated `master` tree isn't enough to recreate this exact build.

## Blue Diamond v2 backup

I wanted a copy of Blue Diamond that I could keep even if the original download disappeared. The **[Blue Diamond v2 archive](https://github.com/aeae1/openpilot/tree/backup/blue-diamond-v2-2026-09-28/backups/blue-diamond-v2)** has the complete three-file runtime package, its original catalog, SHA-256 checksums, and a compatibility manifest.

The exact archive commit is [`70f4db9d01be4ceb3706c508484055f615e0fa0a`](https://github.com/aeae1/openpilot/tree/70f4db9d01be4ceb3706c508484055f615e0fa0a/backups/blue-diamond-v2).

| Payload | Size |
|---|---:|
| `supercombo-blue-diamond-v2.thneed` | 49,235,840 bytes |
| `navmodel_q_gen1.dlc` | 3,630,942 bytes |
| `supercombo_metadata_gen1.pkl` | 727 bytes |
| **Total model package** | **52,867,509 bytes (52.87 MB / 50.42 MiB)** |

The archive branch descends directly from `f4fbb5b` and preserves its tracked files unchanged, adding only the backup folder. This retains the deployment's code and prebuilt dependencies as well as the custom model package. The model payloads are real Git blobs, not external-download links or LFS pointers.

All three downloaded files matched sunnypilot's published SHA-256 checksums, and they were downloaded back from this GitHub archive and checked again. **The copies installed on my comma haven't been read or hash-compared yet.** So this is a verified copy of the published package, rather than an image of my device or a model training checkpoint. The archive's README and `manifest.json` explain what's included and what's still needed for a restore.

## What I've changed

The comparison to use is [`e8de7d3…f4fbb5b`](https://github.com/aeae1/openpilot/compare/e8de7d3fcd81d4d31c62ee2db53ebf76b7582ca8...f4fbb5bc628da0f363e83c2b7c80e3793327eed3). My final changes before this documentation update touched five runtime Python files and the README. The history has a lot more activity than that because I tried things and reverted them. The list below describes what actually survived.

### 1. Cruise-speed ceiling and button increments

I wanted the cruise buttons to land on sensible numbers. The old behavior could turn an intended 85 → 90 mph adjustment into 85 → 89, then 94. There were several attempts at fixing that; this is where the code ended up.

In [`selfdrive/controls/lib/drive_helpers.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/lib/drive_helpers.py):

- `V_CRUISE_MAX` is **161 km/h**, raised from 145 km/h. That is approximately **100 mph**, not an unlimited cruise speed. This is the software setpoint ceiling; it does not prove that factory ACC accepts every requested speed.
- Imperial increments use the exact `CV.MPH_TO_KPH` conversion, **1.609344**, instead of 1.6.
- Small adjustments are **1 mph**; large adjustments are **5 mph**. Metric adjustments remain 1 km/h and 10 km/h.
- Large adjustments snap toward the next interval boundary when off-grid. An interval-relative tolerance handles values already near a boundary. This is the final implementation of my “85 → 89 / 94” correction.
- I keep **ACC Long Press Reverse ON**, so a short press requests the large adjustment and a long press requests the small adjustment.
- Speed changes are ignored in Park, Reverse, and Neutral. The code also ignores an adjustment below 0.5 m/s when the setpoint is unset, preserves the setpoint when resuming from cruise standstill, and avoids treating a button press that enabled cruise as another adjustment.
- The existing gas-override lower bound and final min/max clipping remain.

These modifications are in the non-PCM-speed helper. The inherited **Custom Stock Longitudinal** feature sets `pcmCruiseSpeed=False` on this supported Chrysler configuration, which makes this helper relevant even though the vehicle still uses factory ACC for longitudinal actuation.

### 2. MADS persistence and lateral eligibility

In [`selfdrive/car/interfaces.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/car/interfaces.py):

- `get_sp_started_mads()` returns the current `CS.madsEnabled` state instead of the old forward-gear/one-second rearming sequence.
- When cruise availability transitions from available to unavailable, the method clears its initialization flags and returns `False`.
- `get_sp_common_state()` no longer uses the original gear, open-door, and seatbelt checks to set `gear_allowed=False`. It assigns **`cs_out.latActive=True`** instead.

I wanted MADS to stay selected when I put it on, including through parking and related interruptions. There is more going on in the code than remembering a toggle, though: **this implementation also changes lateral eligibility.** Those edits live in the shared interface, so their scope extends beyond Chrysler.

This assignment does not mean steering is physically active at every speed or in every situation. `controlsd.py` still combines it with MADS state, minimum speed/standstill, brake behavior, steering faults, calibration, and other conditions. The Chrysler controller and panda also have their own constraints.

### 3. Door, seatbelt, stability-control, and high-speed events

In [`selfdrive/controls/lib/events.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/lib/events.py):

| Event | Personal change | What remains in that event definition |
|---|---|---|
| `doorOpen` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `seatbeltNotLatched` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `espDisabled` | `SOFT_DISABLE` entry commented out | `NO_ENTRY` alert |
| `speedTooHigh` | `WARNING` and `NO_ENTRY` entries commented out | Neither of those entries is active |

My old README said “no warnings about seatbelt/door,” which was too broad: the no-entry definitions are still there. These edits affect disengagement and entry behavior, so they deserve a more precise description than “fewer warnings.” Removing the high-speed event also doesn't change what the model was trained on or establish that it performs reliably at a higher speed.

### 4. NNLC loaded-notification suppression

In [`selfdrive/controls/controlsd.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/selfdrive/controls/controlsd.py), `self.nn_alert_shown` starts as `True`, suppressing the periodic NNLC-loaded notification path. This does not create or force a successful NNLC model load. Absence of that notification is not evidence of which model is running.

### 5. Fork-origin recognition

In [`system/version.py`](https://github.com/aeae1/openpilot/blob/f4fbb5bc628da0f363e83c2b7c80e3793327eed3/system/version.py), `github.com/aeae1/openpilot` was added to `is_comma_remote()`'s recognized-origin list. This changes the code's classification of the remote. It does not make the fork an official comma/sunnypilot build or certify that it was tested.

### Scope of the final changes

After the reversions, my final diff has **no net changes to the Chrysler-specific controller/interface/CAN files, panda safety files, or driver-monitoring code** relative to the sunnypilot baseline above. The shared-interface and event-handling changes are still present, so this doesn't mean the fork behaves identically to upstream.

I like how this works in my car. That is my experience, not validation for everyone else's vehicle. If you're considering using it, read the actual changes above and evaluate them for your hardware. Normal driver supervision is still required.

## Features I use that came from sunnypilot

A lot of what I like was already in sunnypilot. These are existing features I've configured, so I don't want to take credit for writing them:

- **MADS:** independent management of lateral assistance and ACC, with Cruise Main and brake behavior options.
- **Dynamic Lane Profile and custom offsets:** the legacy lane planner and its configurable camera/path biases.
- **NNLC / `NNFF`:** neural-network feedforward in torque lateral control. The enabled NNLC setting can select torque tuning even with “Enforce Torque Lateral Control” off. Exact NNLC model matching depends on the vehicle and EPS firmware; the loaded model filename has not been read from this device.
- **Custom Stock Longitudinal:** manages the requested cruise speed through the vehicle's stock ACC interface. The Pacifica's factory system still performs the longitudinal actuation; this is not full openpilot longitudinal control.
- **Vision-based turn speed control, nudgeless lane-change options, road-edge blocking, Quiet Drive, map/display options, and reverse driver-camera view.**

Blue Diamond v2 is the **driving model**, while the NNLC files are separate **steering-control models**. Backing up one does not identify which specific NNLC model was selected at runtime; the preserved deployment includes its available NNLC files.

### Why the offset and model combination matters

I use **Laneful**, with **Custom Offsets ON**, **Camera Offset −20 cm**, and **Path Offset 0 cm**. That combination matters to the behavior I want to keep. In this release, camera offset is read as an integer number of centimeters and applied to the predicted lane-line coordinates. Path offset is applied to the model path before blending. Lane confidence and width still affect how strongly the planner follows the lane-derived path.

The UI describes a decreasing camera-offset value as biasing the car farther left. This is the legacy lane-planner adjustment used by this setup. It is not a universal mounting calibration, and a newer setting with the same name may use a different implementation, sign convention, or model path. Do not transfer the numerical value between generations without checking the code.

## My current settings

These are my current settings. **They haven't been made the installation defaults yet.** A parameter export is still needed to confirm the complete profile. Device identifiers, network details, credentials, and unrelated car-brand toggles are left out.

### Driving and lane behavior

| Setting | Observed value |
|---|---|
| Driving model | Blue Diamond v2 |
| Dynamic Lane Profile | Laneful |
| Custom Offsets | On |
| Camera Offset – Laneful Only | −20 cm |
| Path Offset | 0 cm |
| MADS | On |
| Toggle MADS with Cruise Main | On |
| Enable ACC+MADS with RES+/SET− | Off |
| Steering Mode After Braking | “Remain Active” appears selected; stored parameter still needs confirmation |
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

If my comma ever needs replacing, I'd like to wipe a new or used comma 3X, load my repo, and get my familiar setup back without hunting through every menu. **That recovery behavior isn't implemented yet.**

Right now, `selfdrive/manager/manager.py` fills in its existing defaults when a parameter is missing. Those defaults don't reproduce all of my preferences. For example:

| Preference | Current code default | My selection |
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

A fresh clone alone won't bring back my whole setup. The custom driving-model files normally live outside the Git checkout at `/data/media/0/models`; model selection and most preferences live in the device's parameter store.

The **future behavior I want** is a named personal profile that applies on a clean installation, leaves any later menu adjustments alone during ordinary boots, and can be reapplied with an explicit “Restore My Setup” action. If I'm using a secondhand comma, I'm assuming it gets wiped first. Device identity, registration, credentials, calibration, and learned values need to belong to the replacement device instead of being blindly copied from the old one.

For an eventual restoration, preserve the exact deployment identity, obtain the matching three model files and verify their checksums, confirm model selection, reapply the documented preferences, and complete the replacement device's own setup/calibration. The archive README records the loader's required parameters. **No automatic restore procedure or clean-device installation has been implemented or tested as part of this documentation/backup work.**

## Lead marker and speed-display idea

I'd considered a calmer lead-car marker with one readable speed value on it. The full screen of metrics is more clutter than I want; I'd mostly just like to see how fast the car ahead is going. But I want a speed I can actually trust. A smooth-looking number isn't enough, so this idea is **paused and not implemented**.

In this branch, `selfdrive/car/chrysler/interface.py` sets **`radarUnavailable=True`**. The Pacifica still has radar and uses it for factory ACC, but this openpilot port doesn't supply usable radar tracks to its lead-processing path. Its vision fallback estimates lead speed from the driving model and ego-speed information. Smoothing the marker or rounding the digits would make it look nicer without establishing accuracy. Unless a reliable source can be demonstrated, I'd rather leave this feature out.

## Notes for future me, or anyone working on this

- Compare against the pinned baseline when auditing personal modifications. Commit messages include experiments and reversions, so counting historical edits overstates the final changes.
- Keep the model/metadata/navigation-model combination together. The stock bundled `supercombo.thneed` is not the custom Blue Diamond v2 file.
- Recover the source matching the prebuilt release before attempting UI changes. The default branch is not a substitute for that investigation.
- Preserve the distinction between a named branch and a commit. This release contains branch-name-dependent behavior; an archive branch should not be assumed to behave identically if installed under its archive name.
- Preserve working behavior when evaluating later models or controls. Model generations, lane planning, offsets, and UI implementations are coupled; a model swap is not automatically a drop-in upgrade.
- The September 2026 work adds documentation and a model archive only. It does not change runtime code, seed preferences, install an update on a device, or add the proposed lead-speed UI.

## Attribution and license

Most of this project comes from [sunnypilot](https://github.com/sunnypilot/sunnypilot), [comma's openpilot](https://github.com/commaai/openpilot), and their contributors, including the people behind the NNLC, mapping, vehicle-support, and UI features. I'm **aeae1**, and the personal changes described here are mine, made with AI assistance and manual editing. This README is meant to explain the result clearly, including the parts my earlier notes didn't capture well.

The repository's existing [LICENSE](LICENSE) and third-party notices remain unchanged. Model provenance is recorded in the backup manifest, and archiving the artifacts does not relicense them. Historical upstream information remains in `CHANGELOGS.md` and `RELEASES.md`; those files describe upstream releases and should not be read as a list of personal modifications.
