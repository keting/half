import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from services import git_service


class GitServiceWorkspaceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_dir = Path(self.temp_dir.name)
        self.repos_dir = self.base_dir / "repos"
        self.workspace_dir = self.base_dir / "workspace"
        (self.repos_dir / "3").mkdir(parents=True)
        (self.workspace_dir / "outputs" / "proj-3").mkdir(parents=True)

        self.original_repos_dir = settings.REPOS_DIR
        self.original_workspace_root = settings.WORKSPACE_ROOT
        settings.REPOS_DIR = str(self.repos_dir)
        settings.WORKSPACE_ROOT = str(self.workspace_dir)
        git_service._workspace_repo_identity.cache_clear()
        self.addCleanup(self._restore_settings)

    def _restore_settings(self):
        settings.REPOS_DIR = self.original_repos_dir
        settings.WORKSPACE_ROOT = self.original_workspace_root
        git_service._workspace_repo_identity.cache_clear()

    def test_read_json_falls_back_to_workspace_when_remote_matches(self):
        target_file = self.workspace_dir / "outputs" / "proj-3" / "plan-4.json"
        target_file.write_text(json.dumps({"tasks": [{"task_code": "TASK-001"}]}), encoding="utf-8")

        with patch("services.git_service.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "git@github.com:example-org/example-repo.git\n"
            data = git_service.read_json(3, "outputs/proj-3/plan-4.json", git_repo_url="git@github.com:example-org/example-repo.git")

        self.assertEqual(data, {"tasks": [{"task_code": "TASK-001"}]})

    def test_read_json_does_not_fall_back_when_remote_differs(self):
        target_file = self.workspace_dir / "outputs" / "proj-3" / "plan-4.json"
        target_file.write_text(json.dumps({"tasks": [{"task_code": "TASK-001"}]}), encoding="utf-8")

        with patch("services.git_service.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "git@github.com:someone/else.git\n"
            data = git_service.read_json(3, "outputs/proj-3/plan-4.json", git_repo_url="git@github.com:example-org/example-repo.git")

        self.assertIsNone(data)

    def test_workspace_repo_identity_reads_git_config_without_git_command(self):
        git_config_dir = self.workspace_dir / ".git"
        git_config_dir.mkdir()
        (git_config_dir / "config").write_text(
            "[remote \"origin\"]\n\turl = git@github.com:example-org/example-repo.git\n",
            encoding="utf-8",
        )

        with patch("services.git_service.subprocess.run") as mock_run:
            identity = git_service._workspace_repo_identity()

        self.assertEqual(identity, "github.com/example-org/example-repo")
        mock_run.assert_not_called()

    def test_ensure_repo_keeps_existing_checkout_when_pull_fails(self):
        with patch("services.git_service.os.path.exists", return_value=True), patch(
            "services.git_service.fetch_repo",
        ) as mock_fetch, patch(
            "services.git_service.pull_repo",
            side_effect=RuntimeError("pull failed"),
        ) as mock_pull:
            repo_dir = git_service.ensure_repo(3, "git@github.com:example-org/example-repo.git")

        self.assertEqual(repo_dir, str(self.repos_dir / "3"))
        mock_fetch.assert_called_once_with(3)
        mock_pull.assert_called_once_with(3)

    def test_read_json_falls_back_to_remote_tracking_branch(self):
        def run_side_effect(args, check, capture_output, text, timeout):
            command = tuple(args)
            if command[-2:] == ("symbolic-ref", "refs/remotes/origin/HEAD"):
                result = type("Result", (), {})()
                result.stdout = "refs/remotes/origin/main\n"
                return result
            if command[-2] == "show":
                result = type("Result", (), {})()
                result.stdout = json.dumps({"task_code": "TASK-003"})
                return result
            raise AssertionError(f"unexpected command: {command}")

        with patch("services.git_service._workspace_repo_identity", return_value=None), patch(
            "services.git_service.subprocess.run",
            side_effect=run_side_effect,
        ):
            data = git_service.read_json(3, "outputs/proj-3/TASK-003/result.json", git_repo_url="git@github.com:example-org/example-repo.git")

        self.assertEqual(data, {"task_code": "TASK-003"})

    def test_file_exists_uses_remote_tracking_branch(self):
        def run_side_effect(args, check, capture_output, text, timeout):
            command = tuple(args)
            if command[-2:] == ("symbolic-ref", "refs/remotes/origin/HEAD"):
                result = type("Result", (), {})()
                result.stdout = "refs/remotes/origin/main\n"
                return result
            if command[-2] == "show":
                result = type("Result", (), {})()
                result.stdout = '{"ok":true}'
                return result
            raise AssertionError(f"unexpected command: {command}")

        with patch("services.git_service._workspace_repo_identity", return_value=None), patch(
            "services.git_service.subprocess.run",
            side_effect=run_side_effect,
        ):
            exists = git_service.file_exists(3, "outputs/proj-3/TASK-003/result.json", git_repo_url="git@github.com:example-org/example-repo.git")

        self.assertTrue(exists)


if __name__ == "__main__":
    unittest.main()
