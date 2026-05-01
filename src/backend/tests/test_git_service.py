import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from services import git_service


class GitServiceValidateGitUrlTests(unittest.TestCase):
    def test_accepts_git_repository_clone_urls(self):
        valid_urls = [
            "https://github.com/org/repo",
            "https://github.com/org/repo.git",
            "https://gitlab.com/group/repo.git",
            "https://gitlab.com/group/subgroup/repo.git",
            "https://gitee.com/org/repo.git",
            "https://git.example.com/team/repo.git",
            "https://fcc.com/team/repo.git",
            "https://fdic.gov/team/repo.git",
            "https://git.fcompany.com/team/repo.git",
            "git@github.com:org/repo.git",
            "git@gitlab.com:group/repo.git",
            "ssh://git@github.com/org/repo.git",
            "ssh://git@github.com:22/org/repo.git",
            "ssh://git@git.example.com:2222/team/repo.git",
            "ssh://gitea@git.example.com/team/repo.git",
            "ssh://repo@git.example.com/team/repo.git",
        ]

        for url in valid_urls:
            with self.subTest(url=url):
                self.assertEqual(git_service.validate_git_url(f" {url} "), url)

    def test_rejects_non_clone_or_unsafe_git_urls(self):
        invalid_urls = [
            "www.baidu.com",
            "https://www.baidu.com",
            "https://notgithub.com/test/repo",
            "https://github.com/org",
            "https://github.com/org/repo/issues",
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/tree/main",
            "https://gitlab.com/group/repo/-/tree/main",
            "https://github.com/org/repo.git?tab=readme",
            "https://token@github.com/org/repo.git",
            "https://user:pass@git.example.com/team/repo.git",
            "https://bad host/org/repo.git",
            "https://bad_host.example.com/org/repo.git",
            "https://-bad.example.com/org/repo.git",
            "https://bad-.example.com/org/repo.git",
            "https://bad..example.com/org/repo.git",
            "http://github.com/org/repo.git",
            "file:///tmp/repo",
            "ext::ssh -oProxyCommand=calc example.com/repo.git",
            "-uhttps://github.com/org/repo.git",
            "ssh://git@[::1]/org/repo.git",
            "ssh://git@[fe80::1]/org/repo.git",
            "ssh://git@[fd12:3456::1]/org/repo.git",
            "ssh://git@localhost/org/repo.git",
            "ssh://git@127.0.0.1/org/repo.git",
            "ssh://git@169.254.169.254/org/repo.git",
            "ssh://git@bad host/org/repo.git",
            "ssh://git@bad_host.example.com/org/repo.git",
            "ssh://-bad@git.example.com/org/repo.git",
            "ssh://git:secret@git.example.com/org/repo.git",
            "ssh://git.example.com/org/repo.git",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    git_service.validate_git_url(url)

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
        git_service._ensure_repo_last_run.clear()
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

    def test_ensure_repo_sync_retries_retryable_fetch_failure(self):
        with patch("services.git_service.os.path.exists", return_value=True), patch(
            "services.git_service.fetch_repo",
            side_effect=[RuntimeError("network is unreachable"), str(self.repos_dir / "3")],
        ) as mock_fetch, patch(
            "services.git_service.pull_repo",
            return_value=str(self.repos_dir / "3"),
        ) as mock_pull, patch("services.git_service.time.sleep") as mock_sleep:
            status = git_service.ensure_repo_sync(3, "git@github.com:example-org/example-repo.git")

        self.assertTrue(status.fetched)
        self.assertTrue(status.remote_ready)
        self.assertEqual(mock_fetch.call_count, 2)
        mock_pull.assert_called_once_with(3)
        mock_sleep.assert_called_once()

    def test_ensure_repo_sync_uses_ttl_cache(self):
        git_service._ensure_repo_last_run[3] = git_service.time.monotonic()
        with patch("services.git_service.os.path.exists", return_value=True), patch(
            "services.git_service.fetch_repo",
        ) as mock_fetch, patch(
            "services.git_service.pull_repo",
        ) as mock_pull:
            status = git_service.ensure_repo_sync(3, "git@github.com:example-org/example-repo.git")

        self.assertTrue(status.used_cache)
        mock_fetch.assert_not_called()
        mock_pull.assert_not_called()

    def test_ensure_repo_sync_serializes_concurrent_calls_per_project(self):
        release_fetch = threading.Event()
        fetch_calls: list[int] = []

        def fetch_side_effect(project_id):
            fetch_calls.append(project_id)
            release_fetch.wait(timeout=2)
            return str(self.repos_dir / "3")

        with patch("services.git_service.os.path.exists", return_value=True), patch(
            "services.git_service.fetch_repo",
            side_effect=fetch_side_effect,
        ), patch(
            "services.git_service.pull_repo",
            return_value=str(self.repos_dir / "3"),
        ):
            results = []

            def worker():
                results.append(git_service.ensure_repo_sync(3, "git@github.com:example-org/example-repo.git"))

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            release_fetch.set()
            t1.join()
            t2.join()

        self.assertEqual(len(fetch_calls), 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(any(result.used_cache for result in results))

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

    def test_list_dir_prefers_remote_when_requested(self):
        def run_side_effect(args, check, capture_output, text, timeout):
            command = tuple(args)
            if command[-2:] == ("symbolic-ref", "refs/remotes/origin/HEAD"):
                result = type("Result", (), {})()
                result.stdout = "refs/remotes/origin/main\n"
                return result
            if command[-3] == "ls-tree":
                result = type("Result", (), {})()
                result.stdout = "result.md\nusage.json\n"
                return result
            raise AssertionError(f"unexpected command: {command}")

        with patch("services.git_service._workspace_repo_identity", return_value=None), patch(
            "services.git_service.subprocess.run",
            side_effect=run_side_effect,
        ):
            entries = git_service.list_dir(
                3,
                "outputs/proj-3/TASK-003",
                git_repo_url="git@github.com:example-org/example-repo.git",
                prefer_remote=True,
            )

        self.assertEqual(entries, ["result.md", "usage.json"])


if __name__ == "__main__":
    unittest.main()
