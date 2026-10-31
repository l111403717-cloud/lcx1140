"""通过真实 bin/hx 子进程验证公开行为；不导入或复制执行器实现。"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


HX = Path(__file__).resolve().parents[1] / "bin/hx"
BASH = os.environ.get("HX_TEST_BASH")
if not BASH and os.name == "nt":
    git_path = Path(shutil.which("git") or "git")
    BASH = next((str(p / "bin/bash.exe") for p in git_path.parents if (p / "bin/bash.exe").is_file()), None)
BASH = BASH or shutil.which("bash")
PYTHON = Path(sys.executable).as_posix()


class HxIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hx-regression-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "中文 项目"
        self.project.mkdir()
        self.env = os.environ.copy()
        for key in ("HX_PROJECT_ROOT", "HX_TIMEOUT", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        self.env.update(HX_STATE_HOME=str(self.base / "隔离 state"), HX_PYTHON=PYTHON,
                        HX_SHELL=BASH, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=str(self.base.parent), PYTHONDONTWRITEBYTECODE="1",
                        LC_ALL="C.UTF-8")

    def git(self, *args, cwd=None, check=True):
        p = subprocess.run(["git", "-c", "user.name=Harness Test", "-c", "user.email=hx@example.invalid",
                            "-c", "commit.gpgsign=false", *args], cwd=cwd or self.project,
                           env=self.env, capture_output=True, text=True, encoding="utf-8")
        if check:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def init(self, commit=True, cwd=None):
        self.git("init", "-q", cwd=cwd)
        if commit:
            self.git("add", ".", cwd=cwd)
            self.git("commit", "--allow-empty", "-qm", "fixture", cwd=cwd)

    def write(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def register(self, *commands, auto=False):
        self.write(".harness/verify.json", json.dumps(dict(version=1, auto_detect=auto, commands=commands), ensure_ascii=False))

    def check_command(self, name="page", **kwargs):
        self.write("index.html", "<h1>ok</h1>")
        self.write("tests/检查 页面.py", "from pathlib import Path\nassert Path('index.html').read_text(encoding='utf-8') == '<h1>ok</h1>'\nprint('page assertion passed')\n")
        return dict(name=name, argv=[PYTHON, "tests/检查 页面.py"], kind="test", **kwargs)

    def hx(self, *args, cwd=None, payload=None, env=None, expected=None):
        p = subprocess.run([BASH, str(HX), *args], cwd=cwd or self.project,
                           input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                           env=env or self.env, capture_output=True, text=True, encoding="utf-8", timeout=35)
        if expected is not None:
            self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        return p

    def state_file(self, name):
        files = list(Path(self.env["HX_STATE_HOME"]).glob("*/" + name))
        self.assertEqual(len(files), 1, files)
        return files[0]

    def record(self):
        return json.loads(self.state_file("last-verify.json").read_text(encoding="utf-8"))

    def finish_handoff(self):
        self.hx("handoff", expected=0)
        path = self.project / ".harness/PLAN.md"
        path.write_text(path.read_text(encoding="utf-8").replace("TODO(agent)", "已审查：继续既定任务"), encoding="utf-8")

    def test_no_toolchain_never_claims_functional_pass(self):
        self.init()
        self.write("tools/unregistered.py", "raise RuntimeError('must not be discovered')\n")
        p = self.hx("verify", expected=2)
        self.assertIn("RESULT AUDIT_ONLY", p.stdout)
        self.assertEqual(self.record()["functional"], "NOT_RUN")
        self.assertEqual(self.record()["executed"], 0)

    def test_registered_test_and_chinese_space_paths(self):
        self.register(self.check_command())
        self.init()
        self.hx("verify", expected=0)
        data = self.record()
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["commands"][0]["cwd"], str(self.project.resolve()))
        self.assertIn("page assertion passed", Path(data["commands"][0]["log"]).read_text())

    def test_registered_failure_is_real_failure(self):
        self.register(self.check_command())
        self.init()
        self.write("index.html", "broken")
        self.hx("verify", expected=1)
        self.assertEqual(self.record()["functional"], "FAIL")
        self.assertEqual(self.record()["commands"][0]["exit_code"], 1)

    def test_timeout_records_124_and_kills_command(self):
        self.register(dict(name="slow", kind="test", argv=[PYTHON, "-c", "import time; time.sleep(8)"], timeout=0.2))
        self.init()
        begin = time.monotonic()
        self.hx("verify", expected=2)
        self.assertLess(time.monotonic() - begin, 7)
        self.assertEqual(self.record()["commands"][0]["status"], "TIMEOUT")
        self.assertEqual(self.record()["commands"][0]["exit_code"], 124)

    def test_quick_executes_only_first_command_and_reports_gap(self):
        test = self.check_command()
        self.register(dict(name="syntax", argv=[PYTHON, "-c", "import ast; ast.parse('a = 1')"], kind="check"), test)
        self.init()
        self.write("index.html", "broken")
        self.hx("verify", "--quick", expected=2)
        data = self.record()
        self.assertEqual((data["status"], data["functional"], data["executed"], data["planned"]), ("PARTIAL", "NOT_RUN", 1, 2))
        self.hx("verify", expected=1)
        self.assertEqual(self.record()["executed"], 2)

    def test_quick_one_test_can_complete_declared_coverage(self):
        self.register(self.check_command())
        self.init()
        self.hx("verify", "--quick", expected=0)
        self.assertEqual(self.record()["mode"], "quick")

    def test_checks_only_is_not_functional_pass(self):
        command = self.check_command()
        command["kind"] = "check"
        self.register(command)
        self.init()
        self.assertIn("RESULT CHECKS_ONLY", self.hx("verify", expected=2).stdout)

    def test_no_git_and_no_head_are_incomplete_but_run_checks(self):
        self.register(self.check_command())
        self.assertIn("NO_GIT", self.hx("verify", expected=2).stdout)
        self.assertEqual(self.record()["functional"], "PASS")
        self.init(commit=False)
        self.git("add", "index.html")
        self.assertIn("NO_HEAD", self.hx("verify", expected=2).stdout)
        self.assertEqual(self.record()["functional"], "PASS")
        self.assertIn("index.html", self.record()["audit"]["changed_files"])

    def test_git_executable_missing(self):
        env = dict(self.env, PATH="")
        self.assertIn("NO_GIT", self.hx("audit", env=env, expected=2).stdout)

    def test_parent_repository_scope_is_project_only(self):
        self.register(self.check_command())
        parent_file = self.base / "unrelated.txt"
        parent_file.write_text("parent", encoding="utf-8")
        self.init(cwd=self.base)
        parent_file.write_text("parent changed", encoding="utf-8")
        self.hx("verify", expected=0)
        self.assertEqual(self.record()["audit"]["changed_files"], [])
        self.assertEqual(self.record()["root"], str(self.project.resolve()))
        self.write("新的 文件.txt", "new")
        self.hx("verify", expected=0)
        self.assertEqual(self.record()["audit"]["changed_files"], ["新的 文件.txt"])

    def test_git_diff_failure_not_hidden(self):
        self.register(self.check_command())
        self.init()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        # 只损坏临时夹具的 tree 对象：HEAD 仍存在，实际 git diff 必须报错。
        object_path = self.project / ".git/objects" / tree[:2] / tree[2:]
        object_path.chmod(0o600)
        object_path.unlink()
        p = self.hx("verify", expected=2)
        self.assertIn("git diff exit=", p.stdout)
        self.assertEqual(self.record()["audit"]["status"], "INCOMPLETE")
        self.assertIsNone(self.record()["audit"]["changed_files"])
        self.assertEqual(self.record()["functional"], "PASS")

    def test_git_ls_files_failure_not_hidden(self):
        self.init()
        (self.project / ".git/index").write_bytes(b"corrupt-index")
        self.assertIn("INCOMPLETE", self.hx("audit", expected=2).stdout)

    def test_previous_failure_never_becomes_pass_with_equal_error_count(self):
        self.write("tests/fail.py", "raise RuntimeError('old problem')\n")
        self.register(dict(name="failing", kind="test", argv=[PYTHON, "tests/fail.py"]))
        self.init()
        self.hx("baseline", expected=1)
        self.write("tests/fail.py", "raise RuntimeError('different new problem')\n")
        self.hx("verify", expected=1)
        result = self.record()["commands"][0]
        self.assertTrue(result["previous_failure"])
        self.assertFalse(result["matches_previous_output"])
        self.assertEqual(self.record()["status"], "FAIL")
        self.hx("baseline", expected=1)
        self.hx("verify", expected=1)
        self.assertTrue(self.record()["commands"][0]["matches_previous_output"])

    def test_fresh_handoff_can_have_no_functional_tests(self):
        self.init()
        self.hx("verify", expected=2)
        self.finish_handoff()
        p = self.hx("handoff", "--check", expected=0)
        self.assertIn("FRESH", p.stdout)
        self.assertIn("VERIFICATION AUDIT_ONLY", p.stdout)

    def test_fresh_handoff_can_report_failure_or_not_run(self):
        self.init()
        self.finish_handoff()
        self.assertIn("VERIFICATION NOT_RUN", self.hx("handoff", "--check", expected=0).stdout)
        self.register(self.check_command())
        self.write("index.html", "broken")
        self.hx("verify", expected=1)
        self.finish_handoff()
        self.assertIn("VERIFICATION FAIL", self.hx("handoff", "--check", expected=0).stdout)

    def test_source_test_config_and_ignored_helper_invalidate_evidence(self):
        self.register(self.check_command())
        self.write(".gitignore", ".harness/\n")
        self.write(".harness/check helper.py", "value = 1\n")
        self.init()
        for path in ("index.html", "tests/检查 页面.py", ".harness/verify.json", ".harness/check helper.py"):
            with self.subTest(path=path):
                self.hx("verify", expected=0)
                self.finish_handoff()
                file = self.project / path
                original = file.read_text(encoding="utf-8")
                file.write_text(original + "\n", encoding="utf-8")
                self.hx("handoff", "--check", expected=1)
                self.assertIn("VERIFICATION STALE", self.hx("handoff", expected=0).stdout)
                file.write_text(original, encoding="utf-8")

    def test_no_git_source_change_invalidates_evidence(self):
        self.write("code.txt", "before")
        self.hx("verify", expected=2)
        self.finish_handoff()
        self.write("code.txt", "after")
        self.hx("handoff", "--check", expected=1)
        self.assertIn("VERIFICATION STALE", self.hx("handoff", expected=0).stdout)

    def test_committed_change_invalidates_evidence(self):
        self.register(self.check_command())
        self.init()
        self.hx("verify", expected=0)
        self.finish_handoff()
        self.write("new.txt", "change")
        self.git("add", "new.txt")
        self.git("commit", "-qm", "new state")
        self.hx("handoff", "--check", expected=1)

    def test_verifier_mutating_source_cannot_publish_current_pass(self):
        self.write("source.txt", "before")
        self.register(dict(name="mutates", kind="test", argv=[PYTHON, "-c", "from pathlib import Path; Path('source.txt').write_text('after')"]))
        self.init()
        self.hx("verify", expected=2)
        self.assertFalse(self.record()["unchanged"])
        self.assertIn("VERIFICATION STALE", self.hx("handoff", expected=0).stdout)

    def test_log_loss_and_rerun_evidence_are_not_reused_silently(self):
        self.register(self.check_command())
        self.init()
        self.hx("verify", expected=0)
        self.finish_handoff()
        Path(self.record()["commands"][0]["log"]).unlink()
        self.hx("handoff", "--check", expected=1)
        self.assertIn("VERIFICATION STALE", self.hx("handoff", expected=0).stdout)
        self.finish_handoff()
        self.hx("verify", expected=0)
        self.hx("handoff", "--check", expected=1)

    def test_guard_scope_lock_and_regular_development(self):
        self.register(self.check_command())
        self.init()
        def guard(path):
            return json.loads(self.hx("guard", payload=dict(workspacePaths=[str(self.project)], toolCall=dict(args=dict(Path=str(path)))), expected=0).stdout)
        self.assertEqual(guard(self.project / "tests/new.py")["decision"], "allow")
        self.assertEqual(guard(str(self.project) + "-outside/file.txt")["decision"], "ask")
        self.hx("lock", expected=0)
        self.assertEqual(guard(self.project / ".harness/verify.json")["decision"], "deny")
        self.write(".harness/verify.json", (self.project / ".harness/verify.json").read_text(encoding="utf-8") + "\n")
        self.hx("verify", expected=1)
        self.hx("lock", "--refresh", expected=0)
        self.hx("verify", expected=0)

    def test_stop_sees_staged_and_untracked_changes_and_does_not_claim_pass(self):
        self.init()
        self.write("staged.txt", "staged")
        self.git("add", "staged.txt")
        self.write("未跟踪 文件.txt", "untracked")
        p = self.hx("stop", payload=dict(workspacePaths=[str(self.project)]), expected=0)
        self.assertEqual(json.loads(p.stdout), {})
        data = json.loads(self.state_file("last-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(data["verification"], "NOT_RUN")
        self.assertEqual(set(data["changed_files"]), {"staged.txt", "未跟踪 文件.txt"})

    def test_detect_keeps_auto_commands_and_explicit_root(self):
        self.write("package.json", json.dumps(dict(scripts=dict(typecheck="tsc --noEmit", test="node tests.js"))))
        self.register(dict(name="registered", kind="check", argv=[PYTHON, "-V"]), auto=True)
        p = self.hx("--root", str(self.project), "detect", cwd=self.base, expected=0)
        self.assertLess(p.stdout.index("registered"), p.stdout.index("auto:typecheck"))
        self.assertIn("auto:test kind=test", p.stdout)
        self.assertIn("npm run test", p.stdout)

    def test_cwd_registration_and_invalid_config(self):
        self.write("子 目录/input.txt", "ok")
        self.register(dict(name="cwd", kind="test", cwd="子 目录", argv=[PYTHON, "-c", "from pathlib import Path; assert Path('input.txt').read_text() == 'ok'"]))
        self.init()
        self.hx("verify", expected=0)
        self.register(dict(name="escape", kind="test", cwd="..", argv=[PYTHON, "-V"]))
        self.hx("verify", expected=2)
        self.assertEqual(self.record()["executed"], 0)
        self.write(".harness/verify.json", "{invalid")
        self.hx("verify", expected=2)
        self.assertEqual(self.record()["status"], "INCOMPLETE")

    def test_maintenance_of_assertions_is_reviewable_not_banned(self):
        self.write("tests/test_value.py", "assert 1 == 1\n")
        self.init()
        self.write("tests/test_value.py", "assert 2 == 2\n")
        self.assertIn("REVIEW", self.hx("audit", expected=0).stdout)

    def test_missing_command_is_not_run(self):
        self.register(dict(name="missing", kind="test", argv=["hx-command-does-not-exist-9251"]))
        self.init()
        self.hx("verify", expected=2)
        self.assertEqual(self.record()["commands"][0]["status"], "NOT_RUN")
        self.assertEqual(self.record()["executed"], 0)

    def test_quick_partial_functional_coverage(self):
        self.register(self.check_command("first"), self.check_command("second"))
        self.init()
        p = self.hx("verify", "--quick", expected=2)
        self.assertIn("NOT_RUN second", p.stdout)
        self.assertEqual(self.record()["functional"], "PARTIAL")

    def test_timeout_terminates_descendant_process(self):
        marker = self.base / "child survived.txt"
        child = "import time; from pathlib import Path; time.sleep(1.5); Path(" + repr(str(marker)) + ").write_text('survived')"
        parent = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(8)"
        self.register(dict(name="process-tree", kind="test", argv=[PYTHON, "-c", parent], timeout=0.4))
        self.init()
        self.hx("verify", expected=2)
        time.sleep(1.6)
        self.assertFalse(marker.exists(), "超时后后代进程仍在运行")

    def test_old_explicit_lock_is_not_silently_dropped(self):
        self.write("package.json", '{"scripts": {}}')
        self.init()
        # 旧版公开存储格式：sha1(root) 的前 12 位，lock.sha 是 shasum 清单。
        legacy = Path(self.env["HX_STATE_HOME"]) / hashlib.sha1(str(self.project.resolve()).encode()).hexdigest()[:12]
        legacy.mkdir(parents=True)
        (legacy / "lock.sha").write_text("legacy-digest  package.json\n")
        self.assertIn("旧版显式锁", self.hx("audit", expected=2).stdout)
        payload = dict(workspacePaths=[str(self.project)], toolCall=dict(args=dict(Path="package.json")))
        self.assertEqual(json.loads(self.hx("guard", payload=payload, expected=0).stdout)["decision"], "deny")
        self.hx("lock", "--refresh", expected=0)
        self.hx("audit", expected=0)
        self.assertTrue((legacy / "lock.sha").exists())

    def test_hand_edited_machine_evidence_is_not_fresh(self):
        self.init()
        self.hx("verify", expected=2)
        self.finish_handoff()
        file = self.project / ".harness/PLAN.md"
        file.write_text(file.read_text(encoding="utf-8").replace("VERIFICATION AUDIT_ONLY", "VERIFICATION PASS"), encoding="utf-8")
        self.hx("handoff", "--check", expected=1)
        latest = self.state_file("last-verify.json")
        record = self.record()
        record["status"] = "PASS"
        latest.write_text(json.dumps(record), encoding="utf-8")
        self.assertIn("VERIFICATION STALE", self.hx("handoff", expected=0).stdout)

    def test_coverage_suppression_requires_review_including_untracked_files(self):
        self.init()
        self.write("tests/new test.js", "test.skip('behavior', () => {});\n")
        self.assertIn("AUDIT REVIEW", self.hx("audit", expected=2).stdout)
        self.hx("verify", expected=2)
        self.assertEqual(self.record()["status"], "INCOMPLETE")

    @unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "现有 Node/npm 不可用，不安装依赖")
    def test_auto_node_workflow_runs_real_commands_without_install(self):
        self.write("package.json", json.dumps(dict(scripts=dict(
            lint='node -e "require(\'assert\').strictEqual(1, 1)"',
            test='node -e "require(\'assert\').strictEqual(2 + 2, 4)"'))))
        self.init()
        self.hx("verify", "--quick", expected=2)
        self.assertEqual(self.record()["functional"], "NOT_RUN")
        self.hx("verify", expected=0)
        self.assertEqual([c["name"] for c in self.record()["commands"]], ["auto:lint", "auto:test"])

    def test_arguments_are_literal_including_empty_strings(self):
        arguments = ["", "中文 空格", "$(must-not-run);*"]
        code = "import sys; assert sys.argv[1:] == " + repr(arguments)
        self.register(dict(name="arguments", kind="test", argv=[PYTHON, "-c", code, *arguments]))
        self.init()
        self.hx("verify", expected=0)

    def test_portable_copy_and_executor_change_invalidate_evidence(self):
        self.register(self.check_command())
        self.init()
        installed = self.base / "本地 bin"
        installed.mkdir()
        for name in ("hx", "hx.py"):
            shutil.copyfile(HX.parent / name, installed / name)
        def invoke(command):
            return subprocess.run([BASH, str(installed / "hx"), command], cwd=self.project,
                                  env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=20)
        result = invoke("verify")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        core = installed / "hx.py"
        core.write_text(core.read_text(encoding="utf-8") + "\n# executor revision fixture\n", encoding="utf-8")
        result = invoke("handoff")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERIFICATION STALE", result.stdout)

    def test_map_and_handoff_existing_workflow(self):
        self.register(self.check_command())
        self.init()
        self.hx("map-check", expected=2)
        head = self.git("rev-parse", "HEAD").stdout.strip()
        self.write("PROJECT_MAP.md", f"<!-- map-commit: {head} -->\n`tests/检查 页面.py`\n")
        self.hx("map-check", expected=0)
        self.hx("handoff", "--check", expected=3)
        self.hx("verify", expected=0)
        self.hx("handoff", expected=0)
        self.hx("handoff", "--check", expected=2)
        self.finish_handoff()
        self.assertIn("VERIFICATION PASS", self.hx("handoff", "--check", expected=0).stdout)


if __name__ == "__main__":
    unittest.main()
