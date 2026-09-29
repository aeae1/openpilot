import ast
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from selfdrive.manager import pacifica_setup as setup


class PowerLoss(BaseException):
  pass


class FileParams:
  """Filesystem adapter for the prebuilt Params interface, including empty get()."""
  def __init__(self, root):
    self.root = Path(root)
    self.root.mkdir(parents=True, exist_ok=True)
    self.writes = []
    self.reject = set()
    self.fail_after = None
    self.silent_failure = None
    self.clear_keys = set()

  def check_key(self, key):
    if key in self.reject:
      raise ValueError("Unknown key: " + key)
    return key.encode()

  def get_param_path(self, key=""):
    return str(self.root / key)

  def get(self, key, encoding=None):
    p = self.root / key
    value = p.read_bytes() if p.exists() else b""
    return (value.decode(encoding) if encoding else value) if value else None

  def get_bool(self, key):
    return self.get(key) == b"1"

  def put(self, key, value):
    if self.fail_after is not None and len(self.writes) == self.fail_after:
      raise PowerLoss()
    if key != self.silent_failure:
      self.root.joinpath(key).write_bytes(value.encode() if isinstance(value, str) else value)
    self.writes.append(key)

  def put_bool(self, key, value):
    self.put(key, "1" if value else "0")

  def clear_all(self, flag):
    for key in self.clear_keys:
      (self.root / key).unlink(missing_ok=True)


class SetupTests(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.params = FileParams(self.root / "params/d")
    self.bundle = self.root / "bundle"
    self.bundle.mkdir()
    self.models = self.root / "models"
    self.state = self.root / "setup/state.json"
    self.profile, _ = setup.load_profile()
    # Small payloads exercise the same copy/hash/rename code. Real payloads are
    # independently checked against the device's exported hashes below.
    for entry in self.profile["files"]:
      content = ("test payload for " + entry["name"]).encode()
      (self.bundle / entry["name"]).write_bytes(content)
      entry["bytes"] = len(content)
      entry["sha256"] = hashlib.sha256(content).hexdigest()
    self.profile_path = self.root / "profile.json"
    self.save_profile()

  def save_profile(self):
    self.profile_path.write_text(json.dumps(self.profile))

  def run_setup(self):
    return setup.initialize(self.params, setup.is_clean_install(self.params),
                            self.profile_path, self.bundle, self.models, self.state)

  def restore(self):
    setup.request_restore(self.params, self.profile_path, self.bundle, self.state)

  def assert_installed(self):
    for k, v in {**self.profile["preferences"], **setup.MODEL_SELECTION}.items():
      self.assertEqual(self.params.get(k), v.encode(), k)
    setup.verify_models(self.profile, self.models)
    self.assertEqual(setup.read_state(self.state)["phase"], "complete")

  def test_clean_install_with_os_setup_values(self):
    for key, value in {"DongleId": "keep-identity", "GithubSshKeys": "keep-key",
                       "MapdVersion": "v1.8.0", "HasAcceptedTerms": "0",
                       "CompletedTrainingVersion": "0"}.items():
      self.params.put(key, value)
    self.assertEqual(self.run_setup(), "profile_installed")
    self.assert_installed()
    self.assertEqual(self.params.get("DongleId"), b"keep-identity")
    self.assertEqual(self.params.get("GithubSshKeys"), b"keep-key")
    self.assertEqual(self.params.get("HasAcceptedTerms"), b"0")
    self.assertEqual(self.params.get("CompletedTrainingVersion"), b"0")
    self.assertEqual(self.params.writes[-1], "CustomDrivingModel")

  def test_existing_installation_is_a_complete_noop(self):
    self.params.put("CameraOffset", "-17")
    self.params.put("CustomDrivingModel", "0")
    self.params.put("CalibrationParams", "keep-calibration")
    before = {p.name: p.read_bytes() for p in self.params.root.iterdir()}
    self.params.writes.clear()
    # Existing installs do not even require access to a valid model bundle.
    (self.bundle / self.profile["files"][0]["name"]).unlink()
    self.assertEqual(self.run_setup(), "existing_installation_unchanged")
    self.assertEqual(self.params.writes, [])
    self.assertEqual(before, {p.name: p.read_bytes() for p in self.params.root.iterdir()})
    self.assertFalse(self.state.parent.exists())
    self.assertFalse(self.models.exists())

  def test_any_existing_evidence_prevents_initialization(self):
    for key in setup.PREFERENCE_KEYS | set(setup.MODEL_SELECTION) | setup.INSTALL_EVIDENCE:
      with self.subTest(key=key):
        path = self.params.root / key
        path.write_bytes(b"")  # Even an empty file is evidence.
        self.assertFalse(setup.is_clean_install(self.params))
        path.unlink()
    self.params.put("HasAcceptedTerms", "2")
    self.assertFalse(setup.is_clean_install(self.params))

  def test_reboots_keep_adjustments_and_different_model(self):
    self.run_setup()
    self.params.put("CameraOffset", "-16")
    self.params.put("CustomDrivingModel", "0")
    self.params.root.joinpath("IsMetric").unlink()
    self.params.writes.clear()
    before = self.state.read_bytes()
    self.profile["preferences"]["CameraOffset"] = "15"
    self.save_profile()
    for _ in range(3):
      self.assertEqual(self.run_setup(), "already_initialized")
    self.assertEqual(self.params.writes, [])
    self.assertEqual(self.params.get("CameraOffset"), b"-16")
    self.assertEqual(self.params.get("CustomDrivingModel"), b"0")
    self.assertIsNone(self.params.get("IsMetric"))
    self.assertEqual(self.state.read_bytes(), before)

  def test_missing_marker_never_forces_existing_profile(self):
    self.run_setup()
    self.state.unlink()
    self.params.put("CameraOffset", "8")
    self.params.writes.clear()
    self.assertEqual(self.run_setup(), "existing_installation_unchanged")
    self.assertEqual(self.params.writes, [])
    self.assertEqual(self.params.get("CameraOffset"), b"8")

  def test_corrupt_source_cannot_change_preferences_or_existing_files(self):
    self.models.mkdir()
    old = self.models / self.profile["files"][0]["name"]
    old.write_bytes(b"original")
    last = self.bundle / self.profile["files"][-1]["name"]
    last.write_bytes(b"corrupt")
    with self.assertRaises(setup.SetupError):
      self.run_setup()
    self.assertEqual(old.read_bytes(), b"original")
    self.assertEqual(self.params.writes, [])
    self.assertFalse(self.state.exists())

  def test_unknown_native_parameter_stops_before_install(self):
    self.params.reject.add("CameraOffset")
    with self.assertRaisesRegex(setup.SetupError, "unsupported"):
      self.run_setup()
    self.assertEqual(self.params.writes, [])
    self.assertFalse(self.models.exists())
    self.assertFalse(self.state.exists())

  def test_disk_full_is_resumable_and_cannot_select_unverified_model(self):
    with patch.object(setup.shutil, "copyfileobj", side_effect=OSError(errno.ENOSPC, "full")):
      with self.assertRaises(OSError):
        self.run_setup()
    self.assertEqual(setup.read_state(self.state)["phase"], "pending")
    self.assertEqual(self.params.writes, [])
    self.assertEqual(self.run_setup(), "profile_installed")
    self.assert_installed()

  def test_corrupt_copy_is_rejected_before_parameter_writes(self):
    with patch.object(setup.shutil, "copyfileobj", side_effect=lambda src, dst, size: dst.write(b"bad")):
      with self.assertRaises(setup.SetupError):
        self.run_setup()
    self.assertEqual(self.params.writes, [])
    self.assertNotEqual(setup.read_state(self.state)["phase"], "complete")
    self.run_setup()
    self.assert_installed()

  def test_interruption_at_every_parameter_write_resumes(self):
    count = len(self.profile["preferences"]) + len(setup.MODEL_SELECTION)
    for boundary in range(count):
      with self.subTest(boundary=boundary):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
          root = Path(folder)
          params = FileParams(root / "params")
          state = root / "state/state.json"
          models = root / "models"
          params.fail_after = boundary
          with self.assertRaises(PowerLoss):
            setup.initialize(params, True, self.profile_path, self.bundle, models, state)
          self.assertEqual(setup.read_state(state)["phase"], "pending")
          params.fail_after = None
          self.assertEqual(setup.initialize(params, False, self.profile_path, self.bundle, models, state), "profile_installed")
          for key, val in {**self.profile["preferences"], **setup.MODEL_SELECTION}.items():
            self.assertEqual(params.get(key), val.encode())
          self.assertEqual(setup.read_state(state)["phase"], "complete")

  def test_silent_native_write_failure_is_detected(self):
    self.params.silent_failure = "CameraOffset"
    with self.assertRaisesRegex(setup.SetupError, "CameraOffset"):
      self.run_setup()
    self.assertEqual(setup.read_state(self.state)["phase"], "pending")
    self.assertIsNone(self.params.get("CustomDrivingModel"))
    self.params.silent_failure = None
    self.run_setup()
    self.assert_installed()

  def test_interruption_after_each_model_rename_resumes(self):
    real_replace = os.replace
    for entry in self.profile["files"]:
      with self.subTest(file=entry["name"]), tempfile.TemporaryDirectory(dir=self.root) as folder:
        root = Path(folder)
        params = FileParams(root / "params")
        models = root / "models"
        state = root / "state/state.json"
        def interrupted_replace(src, dst):
          real_replace(src, dst)
          if Path(dst) == models / entry["name"]:
            raise PowerLoss()
        with patch.object(setup.os, "replace", side_effect=interrupted_replace):
          with self.assertRaises(PowerLoss):
            setup.initialize(params, True, self.profile_path, self.bundle, models, state)
        self.assertEqual(params.writes, [])
        self.assertEqual(setup.read_state(state)["phase"], "pending")
        setup.initialize(params, False, self.profile_path, self.bundle, models, state)
        setup.verify_models(self.profile, models)
        self.assertEqual(setup.read_state(state)["phase"], "complete")

  def test_unrelated_models_are_preserved(self):
    self.models.mkdir()
    unrelated = self.models / "another-model.thneed"
    unrelated.write_bytes(b"keep this model")
    (self.models / ".pacifica-abandoned.tmp").write_bytes(b"incomplete old copy")
    self.run_setup()
    self.assertEqual(unrelated.read_bytes(), b"keep this model")
    self.assertEqual(list(self.models.glob(".pacifica-*.tmp")), [])

  def test_null_values_and_wrong_model_generation_are_rejected(self):
    self.profile["preferences"]["IsMetric"] = None
    self.save_profile()
    with self.assertRaises(setup.SetupError):
      self.run_setup()
    self.profile["preferences"]["IsMetric"] = "0"
    self.profile["model_selection"]["DrivingModelGeneration"] = "2"
    self.save_profile()
    with self.assertRaises(setup.SetupError):
      self.run_setup()
    self.assertEqual(self.params.writes, [])

  def test_restore_rechecks_offroad_after_slow_preflight(self):
    self.params.put("IsOffroad", "1")
    self.params.writes.clear()
    def car_started(*args):
      self.params.put("IsOnroad", "1")
    with patch.object(setup, "_preflight", side_effect=car_started):
      with self.assertRaises(setup.SetupError):
        self.restore()
    self.assertFalse(self.state.exists())
    self.assertNotIn("DoReboot", self.params.writes)

  def test_complete_marker_failure_resumes_without_duplicate_model_copy(self):
    original = setup._write_state
    def fail_complete(path, state):
      if state["phase"] == "complete":
        raise PowerLoss()
      return original(path, state)
    with patch.object(setup, "_write_state", side_effect=fail_complete):
      with self.assertRaises(PowerLoss):
        self.run_setup()
    self.assertEqual(setup.read_state(self.state)["phase"], "pending")
    with patch.object(setup.shutil, "copyfileobj", side_effect=AssertionError("unnecessary copy")):
      self.run_setup()
    self.assert_installed()

  def test_interrupted_setup_rejects_changed_profile(self):
    self.params.fail_after = 4
    with self.assertRaises(PowerLoss):
      self.run_setup()
    self.params.fail_after = None
    self.profile["preferences"]["CameraOffset"] = "9"
    self.save_profile()
    before = list(self.params.writes)
    with self.assertRaisesRegex(setup.SetupError, "changed during setup"):
      self.run_setup()
    self.assertEqual(self.params.writes, before)

  def test_restore_only_queues_and_reboots_then_applies_at_startup(self):
    self.run_setup()
    self.params.put("CameraOffset", "10")
    self.params.put("CalibrationParams", "unchanged")
    self.params.put("IsOffroad", "1")
    self.params.writes.clear()
    self.restore()
    self.assertEqual(self.params.writes, ["DoReboot"])
    self.assertEqual(self.params.get("CameraOffset"), b"10")
    self.assertEqual(setup.read_state(self.state)["phase"], "restore_requested")
    self.run_setup()
    self.assert_installed()
    self.assertEqual(self.params.get("CalibrationParams"), b"unchanged")

  def test_restore_rejects_onroad_or_unknown_state(self):
    for onroad, offroad in (("1", "1"), ("0", "0"), ("1", "0")):
      with self.subTest(onroad=onroad, offroad=offroad):
        self.params.put("IsOnroad", onroad)
        self.params.put("IsOffroad", offroad)
        with self.assertRaises(setup.SetupError):
          self.restore()
        self.assertFalse(self.state.exists())

  def test_malformed_profile_and_journal_stop_safely(self):
    self.profile["preferences"]["CalibrationParams"] = "must not import"
    self.save_profile()
    with self.assertRaises(setup.SetupError):
      self.run_setup()
    self.assertEqual(self.params.writes, [])
    self.state.parent.mkdir(exist_ok=True)
    self.state.write_text("{broken")
    with self.assertRaises(setup.SetupError):
      self.run_setup()

  def test_journal_resumes_in_a_new_process_after_abrupt_exit(self):
    # os._exit skips cleanup/finally. A second interpreter must use only disk state.
    script = '''
import os, sys
from pathlib import Path
from selfdrive.manager.test.test_pacifica_setup import FileParams
from selfdrive.manager import pacifica_setup as setup
params=FileParams(sys.argv[1])
original=params.put
def put(key, value):
  original(key, value)
  if sys.argv[6] == "crash" and len(params.writes) == 17:
    os._exit(99)
params.put=put
setup.initialize(params, setup.is_clean_install(params), *map(Path,sys.argv[2:6]))
'''
    args = [sys.executable, "-c", script, str(self.params.root), str(self.profile_path),
            str(self.bundle), str(self.models), str(self.state)]
    crashed = subprocess.run(args + ["crash"], cwd=setup.ROOT)
    self.assertEqual(crashed.returncode, 99)
    self.assertEqual(setup.read_state(self.state)["phase"], "pending")
    resumed = subprocess.run(args + ["resume"], cwd=setup.ROOT)
    self.assertEqual(resumed.returncode, 0)
    self.assert_installed()

  def test_manager_hook_runs_before_defaults_and_process_imports(self):
    # Execute the real manager_init function with its hardware dependencies stubbed.
    source = (setup.ROOT / "selfdrive/manager/manager.py").read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "manager_init")
    prepared = []
    class StopAfterSetup(Exception):
      pass
    def register(**kwargs):
      self.assert_installed()
      prepared.append(True)
      raise StopAfterSetup()
    globals_ = {
      "save_bootlog": lambda: None, "Params": lambda: self.params, "PC": False,
      "get_short_branch": lambda: "pacifica", "is_release_branch": lambda: False,
      "is_clean_install": setup.is_clean_install,
      "initialize_pacifica": lambda params, clean: setup.initialize(params, clean, self.profile_path, self.bundle, self.models, self.state),
      "ParamKeyType": types.SimpleNamespace(CLEAR_ON_MANAGER_START=1, CLEAR_ON_ONROAD_TRANSITION=2, CLEAR_ON_OFFROAD_TRANSITION=3),
      "cloudlog": types.SimpleNamespace(info=lambda *args: None),
      "custom": types.SimpleNamespace(LongitudinalPersonalitySP=types.SimpleNamespace(standard=2)),
      "VERSION": "v1.8.0", "os": types.SimpleNamespace(getenv=lambda k: None, mkdir=lambda *args: None),
      "datetime": __import__("datetime"), "register": register,
      "get_version": lambda: "0.9.6.1-release", "terms_version": b"2", "training_version": b"0.2.0",
      "get_commit": lambda: "fixture", "get_commit_date": lambda: "fixture",
      "get_origin": lambda: "https://github.com/aeae1/openpilot", "is_tested_branch": lambda: True,
      "is_release_sp_branch": lambda: True,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "manager.py", "exec"), globals_)
    with self.assertRaises(StopAfterSetup):
      globals_["manager_init"]()
    self.assertEqual(prepared, [True])


class PackageTests(unittest.TestCase):
  def test_actual_bundle_matches_device_export_hashes(self):
    expected = {
      "supercombo-blue-diamond-v2.thneed": (49235840, "b298caa4be035dbe25b9158f0ba3d0b59a99e6a695a11fccda98b69f5050f29f"),
      "navmodel_q_gen1.dlc": (3630942, "c808717d073a0bb347f9ba929953c0b2b792ce9997f343f7e44a0b2b0e139132"),
      "supercombo_metadata_gen1.pkl": (727, "1924d0918e1cd5914598be67077aa99413eb346291b6b617fb83c222ea8991b8"),
    }
    profile, _ = setup.load_profile()
    self.assertEqual({f["name"]: (f["bytes"], f["sha256"]) for f in profile["files"]}, expected)
    setup.verify_models(profile, setup.BUNDLE_PATH)
    prefs = profile["preferences"]
    for key, value in {"CameraOffset": "-20", "PathOffset": "0", "DynamicLaneProfile": "0",
                       "CustomOffsets": "1", "NNFF": "1", "IsMetric": "0",
                       "DisengageLateralOnBrake": "0", "AccMadsCombo": "0", "MadsCruiseMain": "1",
                       "CustomStockLong": "1", "ReverseAccChange": "1", "MaxTimeOffroad": "9",
                       "QuietDrive": "1", "TurnVisionControl": "1"}.items():
      self.assertEqual(prefs[key], value, key)

  def test_branch_classification_matches_release_c3(self):
    tree = ast.parse((setup.ROOT / "system/version.py").read_text())
    names = {"RELEASE_BRANCHES", "RELEASE_SP_BRANCHES", "TESTED_BRANCHES",
             "is_tested_branch", "is_release_branch", "is_release_sp_branch", "get_branch_type"}
    nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))
             or (isinstance(n, ast.FunctionDef) and n.name in names)]
    scope = {"cache": lambda f: f}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "version.py", "exec"), scope)
    outcomes = []
    for branch in ("release-c3", "pacifica"):
      scope["get_short_branch"] = lambda b=branch: b
      outcomes.append(tuple(scope[k]() for k in ("is_tested_branch", "is_release_branch", "is_release_sp_branch", "get_branch_type")))
    self.assertEqual(outcomes[0], outcomes[1])
    self.assertEqual(outcomes[0], (True, False, True, "release"))


if __name__ == "__main__":
  unittest.main()
