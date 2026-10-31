# Harness

`bin/hx` 在**当前项目目录**运行验证、范围审计和交接。需要已有 Bash 与 Python 3.9+；Windows 可直接使用 Git Bash 和已安装的 `python`，不需要 `shasum`、Perl 或新增依赖。可用 `HX_PYTHON` 指定解释器。本次开发及回归无需执行 `install.sh`。

`bin/hx` 是薄启动器，标准库执行核心为同目录 `hx.py`；手动复制安装时需一起复制，现有安装脚本也同步链接两者，以兼容 Windows 将链接降级为文件复制的情况。

## 日常使用默认保持轻量

全局提示词模板位于 `gate/micro-gate.md`，Codex 与 Antigravity 共用：问答/只读不验证；普通小改只做最小且足够的相关检查；静态上传复用有效证据，按必要构建、增量上传、目标冒烟执行。遵守项目明确的发布要求，仅新增风险或验证契约变化时补充相应回归；不因文件数或 quick 返回 2 自动升级为全量检查。

不要求每次输出判级、生成 PLAN 或写交接。保留范围保护、未提交修改保护、真实验证和禁止削弱测试的约束；默认简报改动、检查/退出码和未验证项，重要告警如实说明，日志按需展开。修改仓库模板不会自动更新另一台电脑已注入的全局提示词。

## 项目验证命令

在项目根目录创建 `.harness/verify.json`：

```json
{
  "version": 1,
  "auto_detect": true,
  "commands": [
    {
      "name": "页面链接",
      "argv": ["python", "tests/检查 链接.py"],
      "kind": "test",
      "cwd": ".",
      "timeout": 30
    }
  ]
}
```

- `argv` 是逐项参数，不是 Shell（命令行解释器）字符串；中文、空格不需要额外包引号。需要 Shell 语法时，明确登记 `["bash", "tools/check.sh"]`，或 `["bash", "-c", "明确的命令"]`。只登记有授权的项目检查，不会搜索并执行任意脚本。
- `kind: test` 表示项目声明的行为/功能测试；语法、类型、lint（静态规范检查）、构建用 `check`，默认也是 `check`。声明不能替代测试内容审查，工具不会证明命令内确实含有有效断言。
- `cwd` 默认项目根目录，只允许项目内的既有目录；命令、参数、工作目录、时间、退出码和日志都进入证据。`timeout` 单位为秒，默认取 `HX_TIMEOUT`，再默认 300 秒；超时会终止命令进程树。
- 登记命令按数组顺序执行，再追加现有 `package.json`、Cargo、Go、Python、Makefile 自动探测结果。`auto_detect: false` 可只运行登记项。配置格式错误会明确报不完整，不静默退回自动探测。
- 自动探测的类型检查、lint、编译和构建是 `check`；明确的 test/pytest 是 `test`。Makefile 的 `check`/`verify` 内容无法推断，默认 `check`；有行为测试时可显式登记并设 `auto_detect: false`，避免重复运行。
- `.harness/` 可能被旧安装的全局 Git 忽略规则排除。需共享验证契约时，明确将 `.harness/verify.json` 加入版本控制；无需跟踪日志和 PLAN。

在项目根目录执行：

```bash
bash /path/to/harness/bin/hx detect
bash /path/to/harness/bin/hx verify
bash /path/to/harness/bin/hx verify --quick
```

也可 `hx --root "项目绝对路径" verify`，或设置 `HX_PROJECT_ROOT`。相对 `argv` 路径以命令的 `cwd` 为准。**不再自动跳到父 Git 仓库根目录**；从项目的源码子目录调用时，请显式指定项目根目录。Git Bash 会转换命令行及上述环境变量中的 Windows 路径。

`--quick` 保留“只运行第一条”的行为，并输出真实 `executed/planned` 数量。若其余命令未跑，结果为 `PARTIAL`；仅当计划本来只有一个功能测试且审计完整时，quick 才能返回 `PASS`。

## 输出和退出码

| `hx verify` 结果 | 退出码 | 含义 |
| --- | --- | --- |
| `PASS` | 0 | 全部声明的命令通过，至少有一项功能测试，审计完整，执行期间证据输入未变 |
| `FAIL` | 1 | 有实际失败，或显式锁定的验证配置发生变化；历史失败仍算失败 |
| `AUDIT_ONLY` | 2 | 没有命令，仅完成范围审计；功能 `NOT_RUN` |
| `CHECKS_ONLY` | 2 | 已跑检查均通过，但没有功能测试 |
| `PARTIAL` | 2 | quick 只完成部分登记/探测计划 |
| `INCOMPLETE` | 2 | 无 Git/HEAD、Git 命令异常、配置错误、命令不可运行、超时、审计待核查或输入发生变化 |

每次都独立输出 `COVERAGE ... functional=...` 与 `AUDIT ...`。例如无 Git 项目里的行为测试可以为 `functional=PASS`，但总体仍为 `INCOMPLETE`，因为缺少提交基线。`PASS` 只覆盖声明的检查，不代表完整产品验收或不存在缺陷。

命令的实际失败退出码保存在 JSON 和日志摘要中；超时是 `TIMEOUT / 124`，不可执行是 `NOT_RUN / 126或127`。`hx baseline` 记录改前各命令结果，并采用同样的总体退出码；后续只标注 `previous_failure`，不按错误数量或相同输出豁免，不声称没有新增问题。

退出码 2 是覆盖信息，不是禁止普通开发、只读分析或交接的审批门禁。调用方应分别处理 0/1/2，按任务风险补充缺失检查；禁止 `|| true` 后仍宣称通过。`detect`、`lock`、`handoff` 的 0 只表示相应操作完成，不能解释为验证通过。

## 审计、锁与证据

- `hx audit` 围绕当前项目的路径执行 Git 命令；包含已暂存、未暂存和未跟踪文件。无 Git、无有效 HEAD 或任何 Git 子命令失败均明确报不完整，文件数未知时为 `unknown`。无提交基线仍可运行登记的检查。
- 默认以 HEAD 为比较基线。`hx lock` 显式记录基线提交及验证配置摘要，`hx lock --refresh` 更新配置摘要，复用原基线；不写共享 `refs/harness/base`，也不改动工作区或创建 stash。已有脏改动保留在审计范围。锁是可审查的流程约束，不是文件系统权限隔离。
- 正常断言维护输出审查提示；需核对真实需求和理由。疑似跳过测试或压制检查的新增语句标为 `AUDIT REVIEW / 2`，总体为 `INCOMPLETE`；不能仅靠自动文本匹配认定作弊或合理变更。这不禁止已授权开发，但不能把待核查告警隐去后宣称全部通过。
- 默认状态位于用户的 `.harness-locks`。可设置 **`HX_STATE_HOME`** 为独立目录；回归测试全部使用临时目录，不改变 HOME、全局 Git 配置或真实锁。
- 每轮日志和 `result.json` 位于独立的 `run-*` 目录，`last-verify.json`/`.txt` 指向最新结果；失败日志不被后续重跑覆盖。
- 指纹包括项目根、HEAD、Git 跟踪及未忽略的新文件内容、验证配置、`.harness/` 内的辅助检查、执行器内容和相关运行环境。无 Git 时按项目目录取内容指纹。源码、测试、命令、配置或新提交变化后旧证据失效；日志缺失/变化也不能复用。
- PLAN、state、`.harness/logs`、`runs`、`snapshots`、`wt` 和当前隔离状态目录不进入指纹，避免留证自身导致过期。不要把验证输入放进这些产物目录；Git 忽略的业务文件、依赖安装内容、外部服务及任意环境变量不在完整内容覆盖内。外部状态变化后应重跑，不宣称证据能自动发现所有外部变化。
- 旧版 `last-verify.txt`、错误数量基线与共享 ref 不作为新版本通过证据；升级后重新运行验证。发现当前项目的旧 `lock.sha` 时，审计明确报待迁移，guard 继续保护验证配置；核对已有授权后 `hx lock --refresh` 建立新锁，保留旧文件。新版本使用项目独立状态及 JSON（结构化数据）契约，依赖旧输出逐行执行命令或只解析 PASS/FAIL 的调用方需按本表更新。

## 交接与宿主

`hx handoff` 生成交接骨架，补全 `TODO(agent)` 后运行 `hx handoff --check`：

- `FRESH / 0`：交接指纹及引用证据对应当前状态；另行输出 `VERIFICATION PASS/FAIL/AUDIT_ONLY/STALE/NOT_RUN/...`。
- `STALE / 1`：项目或引用证据发生变化。
- `INCOMPLETE / 2`：交接未补完或无法核验。
- `NO_HANDOFF / 3`：没有交接块。

**FRESH 可以同时伴随功能失败或未验证。** 它只允许复用已确认决策，不足以将模块标记完成。已有失败、缺少工具链的真实状态也能交接；按风险继续工作，不重复索要已有授权。

`guard` 使用宿主 `workspacePaths` 的项目路径、真正的路径边界及同一份隔离锁；普通业务写入不依赖验证 PASS。`stop` 审计暂存和未跟踪变化，并将审计及验证状态分别写入 `last-audit.json/.txt`，保持宿主通知响应 `{}`；钩子退出 0 只是通知完成。未知工作区不会回退到扫描无关父目录。宿主实际是否执行钩子仍取决于它的配置与能力。

## 本地回归

不安装依赖、不执行全局安装。在本仓库运行：

```text
python -B -m unittest discover -s tests -v
```

Windows 测试会优先使用现有 Git 安装的 Bash；也可用 `HX_TEST_BASH` 明确指定 Git Bash 可执行文件，避免系统 `bash.exe` 指向 WSL。测试以真实 `bin/hx` 为子进程，临时创建 Git 项目、中文空格目录和隔离状态；故障注入仅发生在临时夹具内。覆盖结果语义、超时、基线、父仓库、Git 故障、交接失效和宿主消费者。

本仓库在 `.harness/verify.json` 中按“语法检查 → 完整回归”登记命令：

- `hx verify --quick` 只检查 `bin/hx`、`install.sh` 的 Shell 语法，以及执行器和回归测试的 Python 语法；命令超时为 10 秒。正常输出 `PARTIAL / 2`、`executed=1/2`、`functional=NOT_RUN`，不执行那 35 项功能回归。
- `hx verify` 运行语法检查及完整回归；用于执行器/验证契约变更或明确需要完整验收时。回归采用 unittest 的简洁输出，失败详情仍保存在日志。

以上顺序仅是 Harness 本仓库的配置；其他项目按自己的验证命令选择相关检查。复核时将 `HX_STATE_HOME` 设到 `.harness/runs/review-state` 或系统临时目录即可隔离真实用户状态；无需创建 PLAN、地图或安装任何全局集成。
