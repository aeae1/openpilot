"""Install the owner's profile before manager defaults or driving processes run.

Uses the existing Params API, with an external journal so the prebuilt parameter
library and UI do not need rebuilding. Importing this module has no side effects.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "pacifica/profile.json"
BUNDLE_PATH = ROOT / "pacifica/models"
MODEL_PATH = Path("/data/media/0/models")
STATE_PATH = Path("/data/pacifica_setup/state.json")

# Explicit allowlist: never restore identity, credentials, calibration, learned
# state, accepted terms/training, updater targets, or power/driver-monitoring locks.
PREFERENCE_KEYS = frozenset("""
OpenpilotEnabledToggle IsMetric IsLdwEnabled LanguageSetting
DisengageOnAccelerator RecordFront DisableOnroadUploads
EnableMads MadsCruiseMain AccMadsCombo DisengageLateralOnBrake
DynamicLaneProfile CustomOffsets CameraOffset PathOffset
NNFF EnforceTorqueLateral CustomTorqueLateral
TorqueDeadzoneDeg TorqueFriction TorqueMaxLatAccel
LiveTorque LiveTorqueRelaxed TorquedOverride
CustomStockLong ReverseAccChange LongitudinalPersonality
ExperimentalMode ExperimentalLongitudinalEnabled DynamicExperimentalControl
TurnVisionControl TurnSpeedControl VisionCurveLaneless
EnableSlc SpeedLimitControlPolicy SpeedLimitEngageType
SpeedLimitValueOffset SpeedLimitOffsetType
SpeedLimitWarningType SpeedLimitWarningValueOffset SpeedLimitWarningOffsetType
AutoLaneChangeTimer AutoLaneChangeBsmDelay BelowSpeedPause RoadEdge
QuietDrive HandsOnWheelMonitoring
EndToEndLongAlertLead EndToEndLongAlertLight EndToEndLongAlertUI EndToEndLongToggle
BrakeLights StandStillTimer ShowDebugUI DevUIInfo FeatureStatus
OnroadSettings ReverseDmCam TrueVEgoUi HideVEgoUi ChevronInfo
OnroadScreenOff OnroadScreenOffBrightness OnroadScreenOffEvent
BrightnessControl MaxTimeOffroad ScreenRecorder MadsIconToggle CustomBootScreen
ButtonAutoHide CameraControl CameraControlToggle SidebarTemperatureOptions
NavSettingLeftSide NavSettingTime24h MapboxFullScreen Map3DBuildings
RoadName OsmWayTest OsmDbUpdatesCheck CarModel CarModelText
""".split())

MODEL_SELECTION = {
  "CustomDrivingModel": "1",
  "DrivingModelGeneration": "1",
  "DrivingModelName": "Blue Diamond v2 (December 12, 2023)",
  "DrivingModelText": "blue-diamond-v2",
  "DrivingModelMetadataText": "gen1",
  "NavModelText": "gen1",
}
MODEL_FILES = frozenset(("supercombo-blue-diamond-v2.thneed", "navmodel_q_gen1.dlc",
                         "supercombo_metadata_gen1.pkl"))
INSTALL_EVIDENCE = frozenset("""
Version GitCommit GitBranch GitRemote CalibrationParams CarParamsPersistent
CarParamsCache LiveParameters LiveTorqueParameters NNFFCarModel
""".split())


class SetupError(RuntimeError):
  pass


def _require(condition):
  if not condition:
    raise ValueError("Invalid setup data")


def is_clean_install(params):
  """Call BEFORE manager clears transient parameters. Empty files count as saved.

OS setup may already have written identity, networking, and MapdVersion. Those
are not evidence of an existing driving setup. Even one driving setting or an
old installation/calibration marker is sufficient to leave the device alone.
"""
  for key in PREFERENCE_KEYS | set(MODEL_SELECTION) | INSTALL_EVIDENCE:
    if Path(params.get_param_path(key)).exists():
      return False
  for key in ("HasAcceptedTerms", "CompletedTrainingVersion"):
    path = Path(params.get_param_path(key))
    if path.exists() and path.read_bytes() not in (b"", b"0"):
      return False
  return True


def _fsync_dir(path):
  fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
  try:
    os.fsync(fd)
  finally:
    os.close(fd)


def _mkdir(path):
  if not path.exists():
    _mkdir(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    _fsync_dir(path.parent)


@contextlib.contextmanager
def _locked(state_path):
  _mkdir(state_path.parent)
  with (state_path.parent / "lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    yield


def read_state(state_path=STATE_PATH):
  state_path = Path(state_path)
  if not state_path.exists():
    return None
  try:
    state = json.loads(state_path.read_text())
    _require(isinstance(state, dict))
    _require(state["schema"] == 1)
    _require(state["phase"] in ("pending", "complete", "restore_requested"))
    _require(isinstance(state["profile_id"], str) and state["profile_id"])
    _require(re.fullmatch(r"[0-9a-f]{64}", state["profile_sha256"]))
    _require(state["reason"] in ("clean_install", "explicit_restore"))
  except (ValueError, KeyError, TypeError) as exc:
    raise SetupError("Pacifica setup journal is invalid; do not delete it to force defaults.") from exc
  return state


def _write_state(state_path, state):
  temp = None
  try:
    with tempfile.NamedTemporaryFile(mode="w", dir=str(state_path.parent),
                                     prefix=".state-", delete=False) as output:
      temp = Path(output.name)
      json.dump(state, output, sort_keys=True, indent=2)
      output.write("\n")
      output.flush()
      os.fsync(output.fileno())
    os.replace(str(temp), str(state_path))
    _fsync_dir(state_path.parent)
  finally:
    if temp is not None and temp.exists():
      temp.unlink()


def load_profile(profile_path=PROFILE_PATH):
  raw = Path(profile_path).read_bytes()
  try:
    profile = json.loads(raw)
    _require(isinstance(profile, dict))
    _require(profile["schema"] == 1)
    _require(profile["id"] == "pacifica-blue-diamond-v1")
    _require(isinstance(profile["preferences"], dict))
    _require(set(profile["preferences"]) == PREFERENCE_KEYS)
    _require(all(isinstance(v, str) and v and v != "null" for v in profile["preferences"].values()))
    _require(profile["model_selection"] == MODEL_SELECTION)
    _require(len(profile["files"]) == 3)
    _require({f["name"] for f in profile["files"]} == MODEL_FILES)
    for entry in profile["files"]:
      _require(isinstance(entry["bytes"], int) and entry["bytes"] > 0)
      _require(re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]))
  except (ValueError, KeyError, TypeError) as exc:
    raise SetupError("Invalid Pacifica profile; no defaults were applied.") from exc
  return profile, hashlib.sha256(raw).hexdigest()


def _matches(path, entry):
  if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]:
    return False
  digest = hashlib.sha256()
  with path.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest() == entry["sha256"]


def verify_models(profile, directory):
  for entry in profile["files"]:
    if not _matches(Path(directory) / entry["name"], entry):
      raise SetupError("Pacifica model missing or checksum mismatch: " + entry["name"])


def _install_models(profile, bundle_path, model_path):
  # Validate the complete source package before replacing any destination file.
  verify_models(profile, bundle_path)
  _mkdir(model_path)
  for abandoned in model_path.glob(".pacifica-*.tmp"):
    abandoned.unlink()
  for entry in profile["files"]:
    destination = model_path / entry["name"]
    if _matches(destination, entry):
      continue
    temp = None
    try:
      with tempfile.NamedTemporaryFile(dir=str(model_path), prefix=".pacifica-",
                                       suffix=".tmp", delete=False) as output:
        temp = Path(output.name)
        with (bundle_path / entry["name"]).open("rb") as source:
          shutil.copyfileobj(source, output, 1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
      if not _matches(temp, entry):
        raise SetupError("Pacifica model copy failed verification: " + entry["name"])
      os.replace(str(temp), str(destination))
      _fsync_dir(model_path)
    finally:
      if temp is not None and temp.exists():
        temp.unlink()
  verify_models(profile, model_path)


def _preflight(params, profile, bundle_path):
  for key in list(profile["preferences"]) + list(MODEL_SELECTION):
    try:
      params.check_key(key)  # Check the actual prebuilt Params registry.
    except Exception as exc:
      raise SetupError("Pacifica profile parameter is unsupported by this build: " + key) from exc
  verify_models(profile, bundle_path)


def initialize(params, clean_install, profile_path=PROFILE_PATH,
               bundle_path=BUNDLE_PATH, model_path=MODEL_PATH, state_path=STATE_PATH):
  """Only called at manager startup, before defaults and process preparation.

No journal plus an existing installation is a no-op, including missing params.
A completed journal is also a no-op, even if the profile or user settings change.
An interrupted transaction resumes before any driving processes can start.
"""
  state_path, model_path, bundle_path = Path(state_path), Path(model_path), Path(bundle_path)
  state = read_state(state_path)
  if state and state["phase"] == "complete":
    return "already_initialized"
  if state is None and not clean_install:
    return "existing_installation_unchanged"

  with _locked(state_path):
    state = read_state(state_path)
    if state and state["phase"] == "complete":
      return "already_initialized"
    profile, digest = load_profile(profile_path)
    if state and (state["profile_sha256"] != digest or state["profile_id"] != profile["id"]):
      raise SetupError("Pacifica profile changed during setup; restore the original profile before resuming.")
    _preflight(params, profile, bundle_path)
    state = {"schema": 1, "phase": "pending", "profile_id": profile["id"],
             "profile_sha256": digest, "reason": state["reason"] if state else "clean_install"}
    _write_state(state_path, state)
    _install_models(profile, bundle_path, model_path)

    values = dict(profile["preferences"])
    values.update(MODEL_SELECTION)
    # Enable the custom model only after all files and its other selection keys.
    for key in [k for k in values if k != "CustomDrivingModel"] + ["CustomDrivingModel"]:
      params.put(key, values[key])
      if params.get(key) != values[key].encode("utf-8"):
        raise SetupError("Pacifica preference write did not persist: " + key)
    for key, value in values.items():
      if params.get(key) != value.encode("utf-8"):
        raise SetupError("Pacifica preference verification failed: " + key)
    _fsync_dir(Path(params.get_param_path()))
    state["phase"] = "complete"
    _write_state(state_path, state)
    return "profile_installed"


def request_restore(params, profile_path=PROFILE_PATH, bundle_path=BUNDLE_PATH, state_path=STATE_PATH):
  """Queue an explicit restore for the next boot; never apply settings live."""
  if params.get_bool("IsOnroad") or not params.get_bool("IsOffroad"):
    raise SetupError("Park, turn the car off, and wait for the offroad screen before requesting a restore.")
  profile, digest = load_profile(profile_path)
  _preflight(params, profile, bundle_path)
  state_path = Path(state_path)
  with _locked(state_path):
    if params.get_bool("IsOnroad") or not params.get_bool("IsOffroad"):
      raise SetupError("Device left the offroad state; restore was not queued.")
    state = read_state(state_path)
    if state and state["phase"] == "pending":
      raise SetupError("An interrupted Pacifica setup is already pending; reboot to resume it.")
    _write_state(state_path, {"schema": 1, "phase": "restore_requested", "profile_id": profile["id"],
                             "profile_sha256": digest, "reason": "explicit_restore"})
  if params.get_bool("IsOnroad") or not params.get_bool("IsOffroad"):
    raise SetupError("Restore is queued; device left offroad state. Reboot while parked to apply it.")
  params.put("DoReboot", "1")
  if not params.get_bool("DoReboot"):
    raise SetupError("Restore is queued, but automatic reboot failed. Reboot while parked to apply it.")
