"""hx 的标准库执行核心。退出码：0 完整通过，1 真实失败，2 不完整。"""
import argparse
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tokenize


SCHEMA = 2
CONFIG = ".harness/verify.json"
GENERATED = {".harness/PLAN.md", ".harness/state.json"}
GENERATED_DIRS = {".harness/logs", ".harness/runs", ".harness/snapshots", ".harness/wt"}
SKIP_DIRS = {".git", ".hg", "node_modules", ".venv", "venv", "__pycache__"}
LOCK_GLOBS = ("package.json", "Makefile", "Cargo.toml", "go.mod", "pyproject.toml",
              "requirements*.txt", "*lock*", "tsconfig*.json", "eslint.config.*",
              ".eslintrc*", "vitest.config.*", "jest.config.*", "playwright.config.*")
HANDOFF = r"<!-- HANDOFF BEGIN -->[\s\S]*?<!-- HANDOFF END -->"
BYPASS = r"\.(?:skip|only)\s*\(|@ts-(?:ignore|nocheck)|eslint-disable|type: *ignore|# *noqa|\|\| *true|exit 0"


class Incomplete(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise Incomplete(f"JSON 顶层必须是对象: {path}")
    return value


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def coverage_signal(path, text):
    if path.suffix == ".py":
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            # Python 夹具中的示例字符串不是实际跳过测试；真实忽略指令仍保留。
            text = tokenize.untokenize(t._replace(string="" if t.type == tokenize.STRING else t.string)
                                      for t in tokens)
        except (tokenize.TokenError, IndentationError):
            pass
    return re.search(BYPASS, text)


class Harness:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise Incomplete(f"项目目录不存在: {self.root}")
        self.state_home = Path(os.environ.get("HX_STATE_HOME", str(Path.home() / ".harness-locks"))).resolve()
        self.state = self.state_home / digest(str(self.root).encode())[:16]
        self.config = self.root / CONFIG
        self.shell = os.environ.get("HX_SHELL", "bash")

    def legacy_lock(self):
        if (self.state / "lock.json").exists():
            return None
        roots = [str(self.root)]
        if os.name == "nt":
            roots.append("/" + self.root.drive[0].lower() + self.root.as_posix()[2:])
        for root in roots:
            path = self.state_home / hashlib.sha1(root.encode()).hexdigest()[:12] / "lock.sha"
            if path.exists():
                return path
        return None

    def git(self, *args, ok=(0,)):
        try:
            p = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=self.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Incomplete(f"git {args[0]} 无法完成: {exc}") from exc
        if p.returncode not in ok:
            raise Incomplete(f"git {args[0]} exit={p.returncode}: {p.stderr.decode('utf-8', 'replace').strip()}")
        return p

    def git_info(self):
        if not shutil.which("git"):
            return "NO_GIT", ""
        p = self.git("rev-parse", "--is-inside-work-tree", ok=(0, 128))
        if p.returncode:
            if b"not a git repository" in p.stderr:
                return "NO_GIT", ""
            raise Incomplete(p.stderr.decode("utf-8", "replace").strip())
        if p.stdout.strip() != b"true":
            raise Incomplete("当前目录不是 Git 工作树")
        p = self.git("rev-parse", "--verify", "--quiet", "HEAD", ok=(0, 1))
        return ("HEAD", p.stdout.decode().strip()) if p.returncode == 0 else ("NO_HEAD", "")

    def excluded(self, path):
        rel = path.relative_to(self.root).as_posix()
        return (path == self.state_home or self.state_home in path.parents or
                rel in GENERATED or any(rel == d or rel.startswith(d + "/") for d in GENERATED_DIRS) or
                any(p in SKIP_DIRS for p in path.relative_to(self.root).parts))

    def walk(self, directory):
        files = []
        if not directory.exists():
            return files
        def failed(error):
            raise Incomplete(f"无法列出项目文件: {error}")
        for base, dirs, names in os.walk(directory, onerror=failed):
            dirs[:] = sorted(d for d in dirs if not self.excluded(Path(base) / d))
            files.extend(Path(base) / d for d in dirs if (Path(base) / d).is_symlink())
            files.extend(Path(base) / n for n in sorted(names) if not self.excluded(Path(base) / n))
        return files

    def files(self, git_state):
        if git_state == "NO_GIT":
            paths = self.walk(self.root)
        else:
            p = self.git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".")
            paths = [self.root / os.fsdecode(n) for n in p.stdout.split(b"\0") if n]
            # .harness 往往被全局 gitignore 忽略；控制配置及辅助测试仍进入证据。
            paths += self.walk(self.root / ".harness")
        return sorted(set(p for p in paths if not self.excluded(p)))

    def fingerprint(self):
        state, head = self.git_info()
        h = hashlib.sha256()
        for value in (str(self.root), state, head, sys.executable, sys.version, self.shell,
                      os.environ.get("PATH", ""), os.environ.get("HX_TIMEOUT", "300")):
            h.update(value.encode() + b"\0")
        for path in self.files(state):
            h.update(path.relative_to(self.root).as_posix().encode() + b"\0")
            if path.is_symlink():
                target = path.resolve()
                if not target.is_relative_to(self.root):
                    raise Incomplete(f"证据不能覆盖项目外符号链接: {path}")
                h.update(os.readlink(path).encode() + b"\0")
            if path.is_dir():
                raise Incomplete(f"子模块/目录需单独验证: {path}")
            h.update(path.read_bytes() if path.exists() else b"<deleted>")
            h.update(b"\0")
        for path in (Path(__file__), Path(__file__).with_suffix("")):
            h.update(path.read_bytes())
        for path in (self.state / "lock.json", self.legacy_lock()):
            if path and path.exists():
                h.update(path.read_bytes())
        return h.hexdigest()

    def commands(self):
        timeout = float(os.environ.get("HX_TIMEOUT", "300"))
        commands = []
        def add(name, argv, kind="check", cwd=".", seconds=timeout):
            if (not isinstance(name, str) or not name or
                    not isinstance(argv, list) or not argv or
                    any(not isinstance(a, str) or "\0" in a for a in argv) or not argv[0] or
                    kind not in ("test", "check") or not isinstance(cwd, str) or
                    not isinstance(seconds, (int, float)) or not 0 < seconds <= 86400):
                raise Incomplete("验证命令格式错误（name/argv/kind/cwd/timeout）")
            directory = (self.root / cwd).resolve()
            if not directory.is_relative_to(self.root) or not directory.is_dir():
                raise Incomplete(f"验证工作目录必须位于项目内且存在: {cwd}")
            commands.append(dict(name=name, argv=argv, kind=kind,
                                 cwd=str(directory), timeout=seconds))
        auto = True
        if self.config.exists():
            config = read_json(self.config)
            if (not isinstance(config, dict) or config.get("version") != 1 or
                    not isinstance(config.get("commands"), list) or
                    not isinstance(config.get("auto_detect", True), bool)):
                raise Incomplete(f"{CONFIG} 需要 version=1 和 commands 数组")
            auto = config.get("auto_detect", True)
            for c in config["commands"]:
                if not isinstance(c, dict) or set(c) - {"name", "argv", "kind", "cwd", "timeout"}:
                    raise Incomplete("未知验证命令字段")
                add(c.get("name"), c.get("argv"), c.get("kind", "check"),
                    c.get("cwd", "."), c.get("timeout", timeout))
        if auto:
            package = self.root / "package.json"
            if package.exists():
                data = read_json(package)
                scripts = data.get("scripts", {})
                if not isinstance(scripts, dict):
                    raise Incomplete("package.json scripts 必须是对象")
                pm = next((p for f, p in (("pnpm-lock.yaml", "pnpm"), ("bun.lock", "bun"),
                          ("bun.lockb", "bun"), ("yarn.lock", "yarn")) if (self.root / f).exists()), "npm")
                if (self.root / "tsconfig.json").exists() and not scripts.get("typecheck"):
                    add("auto:typecheck", ["npx", "--no-install", "tsc", "--noEmit"])
                for name in ("typecheck", "lint", "test", "build"):
                    value = scripts.get(name)
                    if value and isinstance(value, str) and "no test specified" not in value:
                        add("auto:" + name, [pm, "run", name], "test" if name == "test" else "check")
            if (self.root / "Cargo.toml").exists():
                add("auto:cargo-check", ["cargo", "check"])
                add("auto:cargo-test", ["cargo", "test"], "test")
            if (self.root / "go.mod").exists():
                add("auto:go-vet", ["go", "vet", "./..."])
                add("auto:go-test", ["go", "test", "./..."], "test")
            if any((self.root / f).exists() for f in ("pyproject.toml", "requirements.txt")):
                add("auto:compile", [sys.executable, "-m", "compileall", "-q", "-x", r"(\.venv|node_modules)", "."])
                if shutil.which("ruff"):
                    add("auto:ruff", ["ruff", "check", "."])
                if (self.root / "tests").is_dir():
                    add("auto:pytest", [sys.executable, "-m", "pytest", "-q"], "test")
            makefile = self.root / "Makefile"
            if makefile.exists():
                content = makefile.read_text(encoding="utf-8")
                for target in ("check", "verify", "test"):
                    if re.search(rf"^{target}\s*:", content, re.M):
                        add("auto:make-" + target, ["make", target], "test" if target == "test" else "check")
                        break
        if len({c["name"] for c in commands}) != len(commands):
            raise Incomplete("验证命令 name 必须唯一")
        return commands

    def prepare_state(self):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "repo_root").write_text(str(self.root), encoding="utf-8")

    def execute(self, c, log):
        started = stamp()
        begin = time.monotonic()
        status, rc = "NOT_RUN", 127
        with log.open("wb") as output:
            try:
                p = subprocess.Popen([self.shell, "-c", "exec " + shlex.join(c["argv"])],
                                     cwd=c["cwd"], stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=os.name != "nt",
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                try:
                    rc = p.wait(timeout=c["timeout"])
                    status = "PASS" if rc == 0 else ("NOT_RUN" if rc in (126, 127) else "FAIL")
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        taskkill = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe")
                        subprocess.run([taskkill, "/PID", str(p.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    else:
                        os.killpg(p.pid, signal.SIGKILL)
                    p.wait(timeout=10)
                    status, rc = "TIMEOUT", 124
            except OSError as exc:
                output.write(str(exc).encode("utf-8"))
        return dict(c, status=status, exit_code=rc, started_at=started, finished_at=stamp(),
                    seconds=round(time.monotonic() - begin, 3), log=str(log),
                    output_sha256=digest(log.read_bytes()))

    def locked_files(self):
        files = [p for p in self.root.iterdir() if p.is_file() and any(fnmatch.fnmatch(p.name, g) for g in LOCK_GLOBS)]
        if self.config.exists():
            files.append(self.config)
        return {p.relative_to(self.root).as_posix(): digest(p.read_bytes()) for p in sorted(files)}

    def audit(self):
        notes, changed = [], set()
        status, head = self.git_info()
        result = "PASS" if status == "HEAD" else "INCOMPLETE"
        if self.legacy_lock():
            result = "INCOMPLETE"
            notes.append("存在旧版显式锁：保留原文件，核对既有授权后 hx lock --refresh 迁移")
        base = head
        lock = self.state / "lock.json"
        if lock.exists():
            data = read_json(lock)
            base = data.get("base") or head
            if data.get("files") != self.locked_files():
                result = "FAIL"
                notes.append("已明确锁定的验证入口/配置发生变化；核对已有授权与理由后 hx lock --refresh")
        if status != "HEAD":
            notes.append(f"{status}: 缺少可比较的提交基线，不能判断没有回归")
        if status != "NO_GIT":
            if base:
                diff = self.git("diff", "--relative", "--no-ext-diff", "--no-textconv", "--no-renames", "-U0", base, "--", ".", ":(exclude,glob)**/*.md").stdout.decode("utf-8", "replace")
                changed.update(os.fsdecode(n) for n in self.git("diff", "--relative", "--no-ext-diff", "--name-only", "-z", base, "--", ".").stdout.split(b"\0") if n)
                if re.search(r"^-.*(?:assert|expect|test\(|it\()", diff, re.M):
                    notes.append("REVIEW: 断言/测试有修改，需核对真实需求、理由与覆盖；不自动判为作弊")
                if re.search(r"^\+[^+].*(?:" + BYPASS + ")", diff, re.M):
                    notes.append("REVIEW: 存在可能影响覆盖的新增语句，需结合上下文审查")
                    if result == "PASS":
                        result = "REVIEW"
            args = ("--cached", "--others") if not head else ("--others",)
            new_files = {os.fsdecode(n) for n in self.git("ls-files", "-z", *args, "--exclude-standard", "--", ".").stdout.split(b"\0") if n}
            changed.update(new_files)
        else:
            changed.update(p.relative_to(self.root).as_posix() for p in self.files(status))
            new_files = changed
        changed = sorted(n for n in changed if not self.excluded(self.root / n))
        for name in sorted(new_files):
            if self.excluded(self.root / name):
                continue
            path = self.root / name
            if path.is_file() and not path.is_symlink() and path.suffix in (".py", ".js", ".ts", ".tsx", ".sh"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if coverage_signal(path, text):
                    notes.append(f"REVIEW: {name} 含覆盖控制语句，检查是否为合理用法")
                    if result == "PASS":
                        result = "REVIEW"
        return dict(status=result, exit_code=0 if result == "PASS" else (1 if result == "FAIL" else 2),
                    root=str(self.root), base=base or None, changed_files=changed, notes=notes)

    def safe_audit(self):
        try:
            return self.audit()
        except (Incomplete, OSError, ValueError, TypeError) as exc:
            return dict(status="INCOMPLETE", exit_code=2, root=str(self.root),
                        base=None, changed_files=None, notes=[str(exc)])

    @staticmethod
    def audit_lines(audit):
        count = len(audit["changed_files"]) if audit["changed_files"] is not None else "unknown"
        return [f"AUDIT {audit['status']} changed_files={count} base={audit['base'] or 'none'}"] + ["AUDIT NOTE " + n for n in audit["notes"]]

    def verify(self, quick=False, baseline=False):
        self.prepare_state()
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=self.state))
        results, notes, commands = [], [], []
        before = None
        started = stamp()
        previous = {}
        baseline_file = self.state / "baseline.json"
        try:
            before = self.fingerprint()
        except (Incomplete, OSError, ValueError) as exc:
            notes.append(str(exc))
        try:
            if baseline_file.exists():
                previous = read_json(baseline_file)
            commands = self.commands()
            selected = commands[:1] if quick else commands
            for i, c in enumerate(selected):
                result = self.execute(c, run_dir / f"{i + 1}.log")
                key = digest(json.dumps(c, sort_keys=True).encode())
                old = previous.get(key)
                result["previous_failure"] = bool(old and old["status"] == "FAIL")
                # 历史失败只是背景，绝不据此放行或断言没有新问题。
                result["matches_previous_output"] = bool(old and old.get("output_sha256") == result["output_sha256"])
                result["key"] = key
                results.append(result)
        except (Incomplete, OSError, ValueError, TypeError) as exc:
            notes.append(str(exc))
        audit = self.safe_audit()
        try:
            after = self.fingerprint()
        except (Incomplete, OSError, ValueError) as exc:
            after = None
            notes.append(str(exc))
        if not before or before != after:
            notes.append("验证期间文件发生变化或指纹不可用；证据不能用于当前状态")
        failures = any(r["status"] == "FAIL" for r in results) or audit["status"] == "FAIL"
        incomplete = (bool(notes) or audit["status"] != "PASS" or
                      any(r["status"] in ("TIMEOUT", "NOT_RUN") for r in results))
        tests = [r for r in results if r["kind"] == "test"]
        functional = ("FAIL" if any(r["status"] == "FAIL" for r in tests) else
                      "INCOMPLETE" if any(r["status"] != "PASS" for r in tests) else
                      "PASS" if tests else "NOT_RUN")
        not_run = commands[len(results):]
        if functional == "PASS" and any(c["kind"] == "test" for c in not_run):
            functional = "PARTIAL"
        if failures:
            status, rc = "FAIL", 1
        elif incomplete:
            status, rc = "INCOMPLETE", 2
        elif len(results) < len(commands):
            status, rc = "PARTIAL", 2
        elif not results:
            status, rc = "AUDIT_ONLY", 2
        elif not tests:
            status, rc = "CHECKS_ONLY", 2
        else:
            status, rc = "PASS", 0
        executed = sum(r["status"] != "NOT_RUN" for r in results)
        record = dict(schema_version=SCHEMA, root=str(self.root), fingerprint=before,
                      unchanged=bool(before and before == after), started_at=started, finished_at=stamp(),
                      mode="quick" if quick else "full", status=status, exit_code=rc,
                      functional=functional, executed=executed, attempted=len(results), planned=len(commands),
                      commands=results, not_run=not_run, audit=audit, notes=notes,
                      run_record=str(run_dir / "result.json"))
        lines = [f"ROOT {self.root}"]
        for r in results:
            prior = " previous_failure=true（历史失败不代表没有新增问题）" if r["previous_failure"] else ""
            lines.append(f"{r['status']} {r['name']} exit={r['exit_code']}{prior}\n  cwd={r['cwd']} argv={shlex.join(r['argv'])}\n  log={r['log']}")
        if not commands:
            lines.append("NO_COMMANDS 未执行功能测试；可在 .harness/verify.json 登记项目检查")
        lines += [f"NOT_RUN {c['name']}（quick 未选中或执行中断）" for c in not_run]
        lines += self.audit_lines(audit) + ["NOTE " + n for n in notes]
        lines += [f"COVERAGE mode={record['mode']} executed={executed}/{len(commands)} attempted={len(results)} functional={functional}", f"RESULT {status}"]
        output = "\n".join(lines) + "\n"
        save_json(run_dir / "result.json", record)
        if baseline:
            save_json(baseline_file, {r["key"]: r for r in results})
            print("BASELINE recorded（仅记录改前状态，不豁免失败）")
        save_json(self.state / "last-verify.json", record)
        (self.state / "last-verify.txt").write_text(output, encoding="utf-8")
        print(output, end="")
        return rc

    def evidence(self):
        path = self.state / "last-verify.json"
        if not path.exists():
            return "NOT_RUN", "none"
        raw = path.read_bytes()
        data = read_json(path)
        valid = (data.get("schema_version") == SCHEMA and data.get("root") == str(self.root) and
                 data.get("unchanged") and data.get("fingerprint") == self.fingerprint())
        if valid:
            run_record = Path(data.get("run_record", ""))
            valid = run_record.is_file() and run_record.read_bytes() == raw
        if valid:
            for c in data["commands"]:
                log = Path(c["log"])
                if not log.is_file() or digest(log.read_bytes()) != c["output_sha256"]:
                    valid = False
        status = data["status"] if valid else "STALE"
        return status, digest(raw + status.encode())

    def handoff(self, check=False):
        plan = self.root / ".harness/PLAN.md"
        content = plan.read_text(encoding="utf-8") if plan.exists() else "# PLAN\n"
        found = re.search(HANDOFF, content)
        if check and not found:
            print("NO_HANDOFF")
            return 3
        current = self.fingerprint()
        verification, evidence_hash = self.evidence()
        audit = self.safe_audit()
        evidence_section = f"""### ② 验证证据（hx 自动生成，禁止手改）
- VERIFICATION {verification}；FRESH 仅说明交接内容匹配。
- 记录：{self.state / 'last-verify.json'}
- AUDIT {audit['status']}；缺少基线时无法证明没有回归。
"""
        if check:
            block = found.group()
            if "TODO(agent)" in block:
                print("INCOMPLETE (交接内容未补全)")
                return 2
            if (f"fp={current} " not in block or f"evidence={evidence_hash}" not in block or
                    evidence_section not in block):
                print("STALE (项目状态或引用证据已变化)")
                return 1
            print(f"FRESH\nVERIFICATION {verification}（交接新鲜度不代表功能通过）")
            return 0
        names = audit["changed_files"]
        summary = "\n".join(f"- `{n}`：TODO(agent)" for n in (names or [])[:20])
        if names is None:
            summary = "- 审计不完整：TODO(agent) 核对改动清单"
        elif not names:
            summary = "- 当前审计范围内无变更文件"
        elif len(names) > 20:
            summary += f"\n- 共 {len(names)} 个文件，完整清单见 hx audit"
        block = f"""<!-- HANDOFF BEGIN -->
## Handoff
- 时间：{stamp()} · 来源：TODO(agent)
- 指纹：fp={current} evidence={evidence_hash}
### ① 改动摘要
{summary}
{evidence_section.rstrip()}
### ③ 已确认决策
- TODO(agent)
### ④ 未完成 / 风险
- TODO(agent)
### ⑤ 接力 Prompt
> TODO(agent)
<!-- HANDOFF END -->"""
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(re.sub(HANDOFF, lambda _: block, content) if found else content.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
        print(f"HANDOFF written: {plan}\nVERIFICATION {verification}")
        return 0

    def lock(self, refresh=False):
        self.prepare_state()
        state, head = self.git_info()
        previous = self.state / "lock.json"
        data = read_json(previous) if refresh and previous.exists() else {}
        save_json(previous, dict(base=data.get("base") or head, files=self.locked_files()))
        print(f"LOCKED {self.state} base={data.get('base') or head or 'none'}（仅显式锁定配置；不证明功能通过）")
        return 0

    def guard(self, payload):
        args = payload.get("toolCall", {}).get("args", {})
        name = args.get("TargetFile") or args.get("Path") or args.get("AbsolutePath")
        if not name:
            return dict(decision="allow")
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            return dict(decision="ask", reason="Harness: 写入工作区之外")
        lock = self.state / "lock.json"
        if self.legacy_lock() and path.relative_to(self.root).as_posix() in self.locked_files():
            return dict(decision="deny", reason="Harness: 旧版显式锁待迁移；核对已有授权后 hx lock --refresh")
        if lock.exists() and path.relative_to(self.root).as_posix() in read_json(lock).get("files", {}):
            return dict(decision="deny", reason="Harness: 已明确锁定的验证入口；核对既有授权后 hx lock --refresh")
        if path.parent == self.root and path.suffix in (".py", ".sh", ".mjs") and not path.exists():
            return dict(decision="deny", reason="Harness: 临时脚本请写到 .harness/ 或系统临时目录；正式测试放 tests/")
        return dict(decision="allow")

    def stop(self):
        self.prepare_state()
        audit = self.safe_audit()
        try:
            verification, _ = self.evidence()
        except (Incomplete, OSError, ValueError, TypeError) as exc:
            verification = "INCOMPLETE"
            audit["notes"].append(str(exc))
        save_json(self.state / "last-audit.json", dict(audit, verification=verification))
        (self.state / "last-audit.txt").write_text("\n".join(self.audit_lines(audit)) + f"\nVERIFICATION {verification}\n", encoding="utf-8")
        print("{}")
        return 0

    def map_check(self):
        path = self.root / "PROJECT_MAP.md"
        if not path.exists():
            print("NO_MAP")
            return 2
        content = path.read_text(encoding="utf-8")
        anchor = re.search(r"<!--\s*map-commit:\s*([A-Za-z0-9]+)\s*-->", "\n".join(content.splitlines()[:5]))
        if not anchor or anchor[1] == "none":
            print("NO_ANCHOR")
            return 2
        self.git("cat-file", "-e", anchor[1] + "^{commit}")
        diff = self.git("diff", "--name-status", anchor[1] + "..HEAD", "--", ".").stdout.decode("utf-8", "replace")
        structural = sum(line[:1] in "ADR" for line in diff.splitlines() if line)
        missing = [p for p in re.findall(r"`([\w.@\-/]+/[\w.@\-/]*)`", content) if not (self.root / p).exists()]
        stale = bool(missing) or structural >= int(os.environ.get("HX_MAP_THRESHOLD", "5"))
        print(f"{'STALE' if stale else 'FRESH'} (structural={structural}, missing={len(missing)})")
        return int(stale)


def main():
    parser = argparse.ArgumentParser(description="hx 项目验证；在项目目录运行，或显式指定 --root。")
    parser.add_argument("--root", default=os.environ.get("HX_PROJECT_ROOT"))
    parser.add_argument("command", choices=("detect", "verify", "audit", "baseline", "lock", "handoff", "guard", "stop", "map-check", "gc"))
    for flag in ("--quick", "--check", "--refresh"):
        parser.add_argument(flag, action="store_true")
    args = parser.parse_args()
    for flag, cmd in (("quick", "verify"), ("check", "handoff"), ("refresh", "lock")):
        if getattr(args, flag) and args.command != cmd:
            parser.error(f"--{flag} 仅用于 {cmd}")
    hook = args.command in ("guard", "stop")
    try:
        payload = json.load(sys.stdin) if hook else {}
        roots = payload.get("workspacePaths") or []
        root = args.root or (roots[0] if roots else None)
        if hook and not root:
            print(json.dumps(dict(decision="allow", reason="Harness: 工作区未知，检查未执行") if args.command == "guard" else {}))
            return 0
        h = Harness(root or Path.cwd())
        if args.command == "detect":
            for c in h.commands():
                print(f"{c['name']} kind={c['kind']} cwd={c['cwd']} timeout={c['timeout']} argv={shlex.join(c['argv'])}")
            return 0
        if args.command in ("verify", "baseline"):
            return h.verify(args.quick, args.command == "baseline")
        if args.command == "audit":
            audit = h.safe_audit()
            print("\n".join(h.audit_lines(audit)))
            return audit["exit_code"]
        if args.command == "handoff":
            return h.handoff(args.check)
        if args.command == "lock":
            return h.lock(args.refresh)
        if args.command == "guard":
            print(json.dumps(h.guard(payload), ensure_ascii=False))
            return 0
        if args.command == "stop":
            return h.stop()
        if args.command == "map-check":
            return h.map_check()
        if args.command == "gc":
            cleaned = 0
            for d in h.state_home.iterdir() if h.state_home.exists() else []:
                marker = d / "repo_root"
                if d.is_dir() and not d.is_symlink() and d.resolve().parent == h.state_home and marker.is_file():
                    root = marker.read_text(encoding="utf-8").strip()
                    if root and not Path(root).exists():
                        shutil.rmtree(d)
                        cleaned += 1
            print(f"GC cleaned={cleaned}")
            return 0
    except (Incomplete, OSError, ValueError, TypeError, KeyError) as exc:
        if hook:
            print(json.dumps(dict(decision="allow", reason=f"Harness: 检查不完整: {exc}") if args.command == "guard" else {}, ensure_ascii=False))
            return 0
        print(f"INCOMPLETE {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
