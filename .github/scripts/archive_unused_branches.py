"""One-time, explicitly enumerated branch cleanup for aeae1/openpilot."""
import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = "aeae1/openpilot"
MANIFEST = Path("backups/branch-cleanup-2026-09-29/manifest.json")
KEEP = {"master", "pacifica", "release-c3", "backup/blue-diamond-v2-2026-09-28"}
PREFIX = "archive/cleanup-2026-09-29/"


class CleanupError(RuntimeError):
  pass


def require(condition, message):
  if not condition:
    raise CleanupError(message)


class API:
  def __init__(self, token):
    self.token = token

  def call(self, method, path, payload=None, missing_ok=False):
    request = urllib.request.Request(
      "https://api.github.com/repos/" + REPOSITORY + path,
      data=None if payload is None else json.dumps(payload).encode(),
      method=method,
      headers={"Authorization": "Bearer " + self.token,
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "aeae1-openpilot-branch-cleanup"})
    try:
      with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
      if exc.code == 404 and missing_ok:
        return None
      raise CleanupError("GitHub API %s failed for %s %s" % (exc.code, method, path)) from None

  def list_all(self, path):
    result = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 101):
      items = self.call("GET", path + separator + "per_page=100&page=" + str(page))
      require(isinstance(items, list), "Expected a list from GitHub")
      result.extend(items)
      if len(items) < 100:
        return result
    raise CleanupError("Pagination limit reached; refusing an incomplete audit")


def validate(manifest):
  require(manifest.get("schema") == 1, "Unexpected manifest version")
  require(manifest.get("repository") == REPOSITORY, "Wrong repository")
  require(manifest.get("cleanup_id") == "2026-09-29", "Wrong cleanup identifier")
  require(manifest.get("source_default_branch") == "master", "Unexpected default branch")
  retained, candidates = manifest["retained"], manifest["candidates"]
  require(len(retained) == 4 and {b["name"] for b in retained} == KEEP, "Retained branches changed")
  require(len(candidates) == 42, "Expected exactly the 42 audited candidates")
  names = [b["name"] for b in candidates]
  require(len(set(names)) == len(names), "Duplicate candidate")
  require(not KEEP.intersection(names), "A retained branch appears in the deletion list")
  for entry in retained + candidates:
    require(re.fullmatch(r"[0-9a-f]{40}", entry["sha"]) is not None, "Invalid expected commit")
  for entry in candidates:
    require(entry["archive_tag"] == PREFIX + entry["name"], "Unexpected archive tag")
    subprocess.run(["git", "check-ref-format", "refs/heads/" + entry["name"]], check=True)
    subprocess.run(["git", "check-ref-format", "refs/tags/" + entry["archive_tag"]], check=True)


def audit(api, manifest, workflow_sha, after=False):
  require(api.call("GET", "")["default_branch"] == "master", "Default branch changed")
  branches = api.list_all("/branches")
  heads = {b["name"]: b for b in branches}
  candidates = manifest["candidates"]
  expected_names = KEEP if after else KEEP | {b["name"] for b in candidates}
  require(set(heads) == expected_names, "Branch inventory changed; inspect it before continuing")
  for entry in manifest["retained"]:
    expected_sha = workflow_sha if entry["name"] == "master" else entry["sha"]
    require(heads[entry["name"]]["commit"]["sha"] == expected_sha,
            "Retained branch moved: " + entry["name"])
  if not after:
    for entry in candidates:
      current = heads[entry["name"]]
      require(not current["protected"], "Candidate is protected: " + entry["name"])
      require(current["commit"]["sha"] == entry["sha"], "Candidate moved: " + entry["name"])
  candidate_names = {b["name"] for b in candidates}
  for pr in api.list_all("/pulls?state=open"):
    own_head = (pr["head"].get("repo") or {}).get("full_name") == REPOSITORY
    require(pr["base"]["ref"] not in candidate_names and
            not (own_head and pr["head"]["ref"] in candidate_names),
            "An open pull request uses a candidate branch")
  return heads


def tag_path(entry):
  return "/git/ref/tags/" + urllib.parse.quote(entry["archive_tag"], safe="/")


def verify_tag(api, entry):
  reference = api.call("GET", tag_path(entry), missing_ok=True)
  require(reference is not None and reference["object"]["type"] == "commit" and
          reference["object"]["sha"] == entry["sha"],
          "Archive tag is missing or points elsewhere: " + entry["archive_tag"])


def archive(api, candidates):
  for entry in candidates:
    reference = api.call("GET", tag_path(entry), missing_ok=True)
    if reference is None:
      api.call("POST", "/git/refs", {"ref": "refs/tags/" + entry["archive_tag"], "sha": entry["sha"]})
    verify_tag(api, entry)
  # Every archive must be durable and readable before any branch can be deleted.
  for entry in candidates:
    verify_tag(api, entry)


def deletion_command(candidates):
  return (["git", "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null",
           "push", "--atomic", "--porcelain"] +
          ["--force-with-lease=refs/heads/" + b["name"] + ":" + b["sha"] for b in candidates] +
          ["https://github.com/" + REPOSITORY + ".git"] +
          [":refs/heads/" + b["name"] for b in candidates])


def delete_branches(candidates, token):
  # Explicit leases prevent deletion if any candidate changes after our audit.
  # Atomic push makes deletion all-or-nothing across the enumerated branches.
  env = os.environ.copy()
  env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
              "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
              "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + base64.b64encode(
                ("x-access-token:" + token).encode()).decode()})
  result = subprocess.run(deletion_command(candidates), env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
  print(result.stdout)
  require(result.returncode == 0, "Atomic deletion failed; archive tags were retained")


def execute(api, manifest, workflow_sha, delete):
  validate(manifest)
  audit(api, manifest, workflow_sha)
  archive(api, manifest["candidates"])
  audit(api, manifest, workflow_sha)
  delete(manifest["candidates"])
  heads = audit(api, manifest, workflow_sha, after=True)
  for entry in manifest["candidates"]:
    verify_tag(api, entry)
  return {"status": "complete", "repository": REPOSITORY,
          "workflow_commit": workflow_sha, "removed_branch_count": len(manifest["candidates"]),
          "archive_tag_count": len(manifest["candidates"]),
          "retained": {name: value["commit"]["sha"] for name, value in heads.items()},
          "runtime_files_changed": False}


def main():
  require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "This job is restricted to aeae1/openpilot")
  require(os.environ.get("GITHUB_REF") == "refs/heads/master", "This job only runs from master")
  token = os.environ["GH_TOKEN"]
  manifest = json.loads(MANIFEST.read_text())
  result = execute(API(token), manifest, os.environ["GITHUB_SHA"],
                   lambda candidates: delete_branches(candidates, token))
  print(json.dumps(result, indent=2, sort_keys=True))
  Path(os.environ["RUNNER_TEMP"], "branch-cleanup-result.json").write_text(json.dumps(result, indent=2) + "\n")
  summary = "## Branch cleanup completed\n\nArchived and removed 42 inactive branches. Retained:\n\n"
  for name, sha in sorted(result["retained"].items()):
    summary += "- `%s` at `%s`\n" % (name, sha)
  summary += "\nAll 42 original tips remain reachable under `" + PREFIX + "`. No runtime files were changed.\n"
  Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary)


if __name__ == "__main__":
  main()
