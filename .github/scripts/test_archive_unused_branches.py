import copy
import json
import unittest

import archive_unused_branches as cleanup


class FakeAPI:
  def __init__(self, manifest, workflow_sha):
    self.heads = {b["name"]: {"name": b["name"], "protected": False,
                             "commit": {"sha": workflow_sha if b["name"] == "master" else b["sha"]}}
                  for b in manifest["retained"] + manifest["candidates"]}
    self.tags = {}
    self.created = []
    self.prs = []
    self.default = "master"
    self.audit_count = 0
    self.before_second_audit = None
    self.fail_after_creates = None

  def call(self, method, path, payload=None, missing_ok=False):
    if method == "GET" and path == "":
      self.audit_count += 1
      if self.audit_count == 2 and self.before_second_audit:
        self.before_second_audit()
      return {"default_branch": self.default}
    if method == "GET" and path.startswith("/git/ref/tags/"):
      return self.tags.get(path)
    if method == "POST" and path == "/git/refs":
      if self.fail_after_creates is not None and len(self.created) == self.fail_after_creates:
        raise cleanup.CleanupError("Simulated archive write failure")
      tag = payload["ref"].removeprefix("refs/tags/")
      path = cleanup.tag_path({"archive_tag": tag})
      if path in self.tags:
        raise cleanup.CleanupError("Ref already exists")
      self.tags[path] = {"object": {"sha": payload["sha"], "type": "commit"}}
      self.created.append(payload)
      return self.tags[path]
    raise AssertionError((method, path))

  def list_all(self, path):
    if path == "/branches":
      return copy.deepcopy(list(self.heads.values()))
    if path == "/pulls?state=open":
      return copy.deepcopy(self.prs)
    raise AssertionError(path)


class CleanupTests(unittest.TestCase):
  def setUp(self):
    self.manifest = json.loads(cleanup.MANIFEST.read_text())
    self.workflow_sha = "a" * 40
    self.api = FakeAPI(self.manifest, self.workflow_sha)
    self.deletions = []

  def delete(self, candidates):
    for entry in candidates:
      self.assertEqual(self.api.tags[cleanup.tag_path(entry)]["object"]["sha"], entry["sha"])
    for entry in candidates:
      del self.api.heads[entry["name"]]
      self.deletions.append(entry["name"])

  def run_cleanup(self, delete=None):
    return cleanup.execute(self.api, self.manifest, self.workflow_sha, delete or self.delete)

  def test_archive_all_exact_tips_before_any_deletion(self):
    result = self.run_cleanup()
    self.assertEqual(result["status"], "complete")
    self.assertEqual(set(self.api.heads), cleanup.KEEP)
    self.assertEqual(len(self.deletions), 42)
    self.assertEqual(len(self.api.tags), 42)
    for entry in self.manifest["retained"]:
      if entry["name"] != "master":
        self.assertEqual(self.api.heads[entry["name"]]["commit"]["sha"], entry["sha"])

  def test_atomic_push_uses_exact_leases_and_no_retained_ref(self):
    candidates = self.manifest["candidates"]
    command = cleanup.deletion_command(candidates)
    self.assertIn("--atomic", command)
    leases = {arg for arg in command if arg.startswith("--force-with-lease=")}
    deletes = {arg for arg in command if arg.startswith(":refs/heads/")}
    self.assertEqual(leases, {"--force-with-lease=refs/heads/" + b["name"] + ":" + b["sha"] for b in candidates})
    self.assertEqual(deletes, {":refs/heads/" + b["name"] for b in candidates})
    self.assertTrue(all(":refs/heads/" + name not in deletes for name in cleanup.KEEP))
    self.assertIn("https://github.com/aeae1/openpilot.git", command)

  def test_existing_matching_tags_are_reused(self):
    for entry in self.manifest["candidates"]:
      self.api.tags[cleanup.tag_path(entry)] = {"object": {"sha": entry["sha"], "type": "commit"}}
    self.run_cleanup()
    self.assertEqual(self.api.created, [])

  def test_mismatched_archive_prevents_all_deletions(self):
    entry = self.manifest["candidates"][8]
    self.api.tags[cleanup.tag_path(entry)] = {"object": {"sha": "0" * 40, "type": "commit"}}
    with self.assertRaisesRegex(cleanup.CleanupError, "points elsewhere"):
      self.run_cleanup()
    self.assertEqual(self.deletions, [])
    self.assertEqual(len(self.api.heads), 46)

  def test_partial_archive_failure_cannot_delete_any_branch(self):
    self.api.fail_after_creates = 7
    with self.assertRaisesRegex(cleanup.CleanupError, "archive write failure"):
      self.run_cleanup()
    self.assertEqual(len(self.api.tags), 7)
    self.assertEqual(self.deletions, [])
    self.assertEqual(len(self.api.heads), 46)

  def test_changed_protected_or_new_branch_stops_before_archiving(self):
    entry = self.manifest["candidates"][0]
    for change in ("moved", "protected", "new", "default", "retained"):
      with self.subTest(change=change):
        self.api = FakeAPI(self.manifest, self.workflow_sha)
        if change == "moved":
          self.api.heads[entry["name"]]["commit"]["sha"] = "0" * 40
        elif change == "protected":
          self.api.heads[entry["name"]]["protected"] = True
        elif change == "new":
          self.api.heads["new-work"] = {"name": "new-work", "protected": False, "commit": {"sha": "b" * 40}}
        elif change == "default":
          self.api.default = "pacifica"
        else:
          self.api.heads["release-c3"]["commit"]["sha"] = "0" * 40
        with self.assertRaises(cleanup.CleanupError):
          self.run_cleanup()
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.deletions, [])

  def test_changes_during_archival_still_prevent_deletion(self):
    entry = self.manifest["candidates"][0]
    def move_branch():
      self.api.heads[entry["name"]]["commit"]["sha"] = "0" * 40
    self.api.before_second_audit = move_branch
    with self.assertRaisesRegex(cleanup.CleanupError, "Candidate moved"):
      self.run_cleanup()
    self.assertEqual(len(self.api.tags), 42)
    self.assertEqual(self.deletions, [])

  def test_candidate_open_pr_stops_before_archiving(self):
    entry = self.manifest["candidates"][0]
    self.api.prs = [{"head": {"ref": entry["name"], "repo": {"full_name": cleanup.REPOSITORY}},
                     "base": {"ref": "master"}}]
    with self.assertRaisesRegex(cleanup.CleanupError, "open pull request"):
      self.run_cleanup()
    self.assertEqual(self.api.created, [])
    self.assertEqual(self.deletions, [])

  def test_unsafe_manifest_cannot_mutate_refs(self):
    for change in ("wrong_repo", "keep_deletion", "tag_retarget", "duplicate"):
      with self.subTest(change=change):
        self.manifest = json.loads(cleanup.MANIFEST.read_text())
        if change == "wrong_repo":
          self.manifest["repository"] = "another/repo"
        elif change == "keep_deletion":
          self.manifest["candidates"][0]["name"] = "pacifica"
        elif change == "tag_retarget":
          self.manifest["candidates"][0]["archive_tag"] = "v0.9.6.1"
        else:
          self.manifest["candidates"][0] = copy.deepcopy(self.manifest["candidates"][1])
        with self.assertRaises(cleanup.CleanupError):
          self.run_cleanup()
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.deletions, [])

  def test_failed_atomic_push_never_reports_success(self):
    def fail(candidates):
      raise cleanup.CleanupError("Simulated rejected atomic push")
    with self.assertRaisesRegex(cleanup.CleanupError, "rejected atomic push"):
      self.run_cleanup(delete=fail)
    self.assertEqual(len(self.api.tags), 42)
    self.assertEqual(len(self.api.heads), 46)


if __name__ == "__main__":
  unittest.main()
