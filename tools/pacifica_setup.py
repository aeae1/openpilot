#!/usr/bin/env python3
"""Inspect the Pacifica bundle, or explicitly restore it at the next reboot."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from selfdrive.manager.pacifica_setup import (BUNDLE_PATH, MODEL_PATH, STATE_PATH, SetupError,
                                             is_clean_install, load_profile, read_state,
                                             request_restore, verify_models)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  action = parser.add_mutually_exclusive_group(required=True)
  action.add_argument("--verify-bundle", action="store_true", help="Check the bundled model files; no device required")
  action.add_argument("--status", action="store_true", help="Read the device's setup state and installed model hashes")
  action.add_argument("--restore", action="store_true", help="Explicitly restore my saved setup on the next reboot (offroad only)")
  args = parser.parse_args()
  profile, digest = load_profile()
  verify_models(profile, BUNDLE_PATH)
  if args.verify_bundle:
    print("Blue Diamond bundle verified: 3 files, %d bytes." % sum(f["bytes"] for f in profile["files"]))
    return

  from openpilot.common.params import Params
  params = Params()
  if args.status:
    state = read_state()
    print(json.dumps({"profile": profile["id"], "profile_sha256": digest,
                      "state": state, "clean_install_evidence": is_clean_install(params)}, indent=2))
    different = [key for key, value in {**profile["preferences"], **profile["model_selection"]}.items()
                 if params.get(key) != value.encode("utf-8")]
    print("Parameters different or absent (later adjustments are allowed): " + (", ".join(different) or "none"))
    verify_models(profile, MODEL_PATH)
    print("Installed Blue Diamond files also match the bundle.")
    return

  branch = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
  if branch != "pacifica" or not Path("/AGNOS").is_file():
    raise SetupError("Restore requires the pacifica branch installed on the comma device.")
  request_restore(params)
  print("Restore queued in %s. The comma will reboot and apply it before starting its processes." % STATE_PATH)


if __name__ == "__main__":
  try:
    main()
  except (SetupError, OSError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
