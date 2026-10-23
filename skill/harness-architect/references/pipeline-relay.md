# Harness Architect: Pipeline Relay 参考协议

本文是 `harness-architect` 的 Pipeline Relay（多会话流水线接力）详细参考协议。它与 `SKILL.md`、`references/output-template.md` 配套使用，不能降低第 0 步环境门禁和物理权限边界。

## 设计约定

- `PROGRESS.md` 是任务状态、模块依赖和验收证据的唯一可信源（Single Source of Truth，唯一可信源）；代码本身仍以工作区文件为准。
- 每个模块由一个全新会话负责。只有平台确实支持隔离上下文的子代理时才启用自动模式；否则生成接力提示词，由用户在新会话启动。不得声称已经清空当前会话上下文。
- 模块状态严格使用 `TODO`、`IN_PROGRESS`、`DONE`。阻塞原因放在 `blockers`，不能增加伪状态或把未验证模块标成 `DONE`。
- 同一时刻只允许一个写入者更新主 `PROGRESS.md`。并行子代理须有独立文件所有权；由调度器汇总证据并更新主进度文件。

## 1. Handoff Protocol（模块交接协议）

### 1.1 `PROGRESS.md` 标准 Schema

文件以一个 `yaml` 代码块作为唯一权威数据区。代码块外只放简短说明，不重复维护状态。命令必须记录真实执行结果，不允许根据日志推测退出码。

```yaml
schema_version: 1
project: "项目名称"
updated_at: "2025-01-01T12:00:00+08:00"

workflow:
  state: BASELINE_GATE
  mode: MANUAL
  current_module: null
  baseline_gate:
    status: PENDING
    evidence_file: ".harness/gate.json"
    checks:
      - command: "python tools/check_env.py"
        exit_code: null
        result: ""
      - command: "python runner.py check-env"
        exit_code: null
        result: ""
  final_gate:
    status: PENDING
    checks: []

modules:
  - id: M01
    name: "模块名称"
    status: TODO
    depends_on: []
    objective: "可验收的单模块目标"
    prd_refs:
      - "PRD.md#需求章节"
    scope:
      include:
        - "允许修改的目录或文件"
      exclude:
        - "明确禁止修改的目录或行为"
    contracts:
      inputs: []
      outputs: []
      constraints: []
    acceptance:
      - id: M01-A1
        command: "python runner.py verify"
        expected_exit_code: 0
    deliverables:
      expected_files:
        - "src/module.py"
      produced_files: []
    evidence:
      completed_at: null
      revision: null
      checks: []
      summary: ""
    decisions: []
    blockers: []
    next_module_hint: "M02"
```

字段规则：

- `workflow.state` 取值：`BASELINE_GATE`、`PLANNING`、`MODULE_ACTIVE`、`MODULE_VERIFY`、`HANDOFF_READY`、`BLOCKED`、`FINAL_VERIFY`、`COMPLETE`。
- `workflow.mode` 取值：`AUTO` 或 `MANUAL`。`current_module` 只能指向当前唯一施工模块。
- 每个模块必须有稳定的 `id`、目标、依赖、文件范围和至少一条验收命令；无自动测试时，写明可复现的人工验收步骤及其证据形式，不能留空。
- `acceptance.command` 必须是已登记的 `runner.py` 验证入口；不得把未经登记的裸 Shell（命令行）当作验收命令。`evidence.checks` 每项记录 `command`、`exit_code`、`result` 和 `run_at`。代码再次修改后，受影响的旧证据立即失效，必须重跑。
- `produced_files` 记录本模块实际交付；`decisions` 只记录会影响后续模块的结论；`blockers` 记录现状、影响和解除条件。

## 2. Relay 状态机与转换规则

```text
BASELINE_GATE -> PLANNING -> MODULE_ACTIVE -> MODULE_VERIFY
                                      ^              |
                                      | 失败/修复     | 全部验收通过
                                      +--------------+-> HANDOFF_READY
                                                               |
                              仍有可执行模块：MODULE_ACTIVE <---+
                              全部模块 DONE：FINAL_VERIFY -> COMPLETE

任意门禁失败 -> BLOCKED；解除阻塞后回到失败的门禁或当前模块，不跳过失败步骤。
```

- 启动时先完成第 0 步门禁：创建或核验 `tools/check_env.py` 和 `runner.py`，依次真实运行 `python tools/check_env.py`、`python runner.py check-env` 和 `python runner.py status`，三条命令退出码均为 `0`。在此之前不得开始功能施工。
- 模块开工前，所有 `depends_on` 必须为 `DONE`；将当前模块设为 `IN_PROGRESS`。一次只选一个模块，除非已证明无共享文件、无接口冲突且可隔离工作区。
- 只有模块验收和交接硬门禁全部通过，才允许设为 `DONE` 并进入 `HANDOFF_READY`。失败、未运行或退出码不为 `0` 都不算通过。
- 若后续改动破坏已完成模块的验收证据，将受影响模块退回 `IN_PROGRESS`，记录原因并重新验证。
- 全部模块 `DONE` 后进入 `FINAL_VERIFY`；全局门禁通过且需求交付物核对完成后才能进入 `COMPLETE`。

## 3. 会话退出硬门禁

正常模块交接必须全部满足：

1. 当前模块所有 `acceptance` 命令在最终代码状态下真实执行，预期退出码全部为 `0`。
2. 在最终代码状态下依次重跑 `python tools/check_env.py`、`python runner.py check-env`、`python runner.py status` 和 `python runner.py verify`，四条命令本次退出码均为 `0`。不可复用更早运行、代码修改前的结果。
3. 检查本模块的文件变更与 `scope` 一致；`PROGRESS.md` 已写入命令、退出码、结果摘要、交付文件、关键结论和下一模块提示。
4. 检查下一模块依赖均已完成，并且没有未记录的阻塞、接口变更或未解释的测试失败。
5. 更新进度文件后再次确认其模块状态、依赖和证据相互一致，然后才输出下一会话提示词。

任一条件失败时：保留当前模块为 `IN_PROGRESS`，将工作流设为 `BLOCKED`，写清阻塞和重试步骤；不得把失败交接伪装成正常接力，也不得启动下一个模块。若用户明确要求暂停，可输出“恢复当前模块”的提示词，但不得宣称模块完成。

## 4. 接棒会话开场注入协议

新会话按以下顺序读取，不导入旧聊天记录，也不扫描整个仓库：

1. 确认仓库根目录，读取 `PROGRESS.md` 的权威 YAML 区和 `HARNESS.md` 中全局硬规则。
2. 检查当前模块的状态、依赖及基线证据；依赖未完成、模块不存在或状态与提示词冲突时，停止施工并报告冲突。
3. 只读 `PRD.md` 中 `prd_refs` 指向的章节、模块相关接口/决策文档，以及 `scope` 涉及的源文件和邻近测试。
4. 查看 `git status --short` 与本模块相关的差异；不倾倒完整历史、全量日志或无关目录。错误日志只读取错误上下文及必要堆栈。
5. 用简短清单确认：模块目标、依赖、可改范围、禁止范围、接口约束、验收命令、未知项。若资料互相矛盾，先停止并写入阻塞，不自行补造事实。

优先级：用户最新明确指令 > `HARNESS.md` 的安全和工作流约束 > `PRD.md` 的产品行为 > `PROGRESS.md` 的模块状态/已记录决策 > 代理自行推断。状态冲突不得静默覆盖。

## 5. Skill 升级改造方案

### 5.1 可加入 `SKILL.md` 的 Relay Dispatcher 规则

```markdown
## Relay Dispatcher

### 目标
按 PROGRESS.md 串行调度独立模块会话。PROGRESS.md 是任务状态和验收证据的唯一可信源；不得依赖上一会话记忆。

### 启动
1. 检查 tools/check_env.py、runner.py；缺失时先创建最小可验证版本。
2. 真实运行 `python tools/check_env.py`、`python runner.py check-env` 和 `python runner.py status`。三条命令退出码均为 0 前，禁止功能施工。
3. 创建/核验 PRD.md、HARNESS.md 和 PROGRESS.md，拆解模块、依赖、范围和验收命令。
4. 选择依赖全部 DONE 的模块，将其设为 IN_PROGRESS。

### 调度
- 状态只能是 TODO、IN_PROGRESS、DONE。未有全部验收证据不得写 DONE。
- 优先每个模块使用一个全新会话。仅在运行环境明确提供隔离子代理时使用 AUTO；否则使用 MANUAL 并打印接力提示词。
- 默认串行。只有模块依赖无关、文件所有权不重叠、接口已冻结且工作区隔离时，才允许并行。
- 子代理只接收当前模块任务包，不继承整个对话。主调度器负责合并结果并串行更新主 PROGRESS.md。
- 子代理返回内容必须包含：模块 ID、变更文件、实际命令及退出码、验收结果、接口/决策变化、阻塞、下一步。缺项视为未交付。

### 验收与交接
- 最终代码状态下运行模块验收命令、`python tools/check_env.py`、`python runner.py check-env`、`python runner.py status` 和 `python runner.py verify`；全部真实退出码为 0 才能交接。
- 任一命令失败、无法运行或结果过期：模块维持 IN_PROGRESS，workflow.state=BLOCKED；修复当前模块，不调度下一模块。
- 门禁通过后记录证据、交付文件和决定，将模块标为 DONE，再选择依赖已满足的下一模块。
- AUTO 模式由调度器逐个启动隔离子代理；不得让多个代理并发写主进度文件。
- MANUAL 模式打印“下一会话接力提示词”，然后结束当前模块会话；不得假定新会话已经启动。
- 所有模块 DONE 后运行最终全局门禁，核对 PRD.md 与 HARNESS.md 要求，再将 workflow.state 设为 COMPLETE。

### 失败与冲突
- 不得伪造退出码、复用过期证据、跳过失败门禁或把阻塞改写成 DONE。
- 需求、接口、文件范围或进度互相冲突时停止相关施工，将冲突和所需决策写入 blockers。
- 未经用户批准不引入外部依赖、不扩大模块范围；改动跨模块时更新依赖并使相关验收证据失效。
```

### 5.2 可加入 `HARNESS.md` 的分工矩阵

| 角色 | 会话范围 | 可写内容 | 必须交付 |
|---|---|---|---|
| Relay Dispatcher（接力调度器） | 项目全局 | 主 `PROGRESS.md`、模块拆分和提示词 | 依赖图、唯一当前模块、门禁证据、下一棒任务包 |
| Module Implementer（模块实施者） | 单个模块/单个新会话 | 当前模块 `scope.include` | 代码、模块测试结果、变更文件、决策和阻塞 |
| Verifier（验收者） | 当前模块或最终集成 | 测试报告；代码仅限明确授权修复 | 实际命令、退出码、失败摘要、需求覆盖结论 |

冲突时遵循最小写权限：实施者不得改其他模块、依赖图或全局门禁；若产品要求迫使跨界，先报告并由调度器调整任务包。子代理不得自行扩大权限。

### 5.3 可加入 `HARNESS.md` 的模块施工流水线

```text
0. Environment Gate：创建/核验环境脚本和 runner，二者实跑退出码 0。
1. Architecture：产出 PRD.md、HARNESS.md；在 PROGRESS.md 拆分模块及依赖。
2. Dispatch：选出依赖已完成的单一模块，冻结接口、文件所有权和验收条件。
3. Fresh Session：按开场协议只读必要文件；确认任务包后施工。
4. Module Verify：运行模块验收；失败则留在当前模块修复。
5. Relay Gate：重跑 `check_env.py`、`runner.py check-env`、`runner.py status` 和 `runner.py verify`；全部退出码 0 后记录证据并置 DONE。
6. Handoff：自动模式调度下一个隔离代理；手动模式打印下一会话提示词。
7. Final Verify：所有模块 DONE 后执行全局测试和需求核对，最终状态置 COMPLETE。
```

### 5.4 子代理防跑偏任务包

每次委派必须从 `PROGRESS.md` 生成一个明确任务包，至少包含：

- `module_id`、唯一目标、完成定义、依赖及其完成证据；
- PRD 章节锚点、必须遵守的接口/数据约定及已确认决定；
- `scope.include` 与 `scope.exclude`，尤其是禁止改动的文件和禁止顺手重构的内容；
- 验收命令、预期退出码、环境前提；
- 未决问题和停止条件；
- 强制回报格式及主进度文件由谁写入。

并行时给每个代理分配不重叠的文件所有权；共享接口先由调度器冻结。任何影响其他模块的发现都作为报告返回，不自行修改邻接模块。这样同时限制输入上下文和变更范围，避免只凭摘要猜测隐含要求。

## 6. 下一会话接力提示词生成器模板

当前模块完成并通过交接门禁后，将占位符替换为 `PROGRESS.md` 中的实际内容，再完整打印以下文本。若无可接模块，改为打印最终集成提示词；若门禁失败，只生成恢复当前模块的提示词。

```text
你是本项目的全新模块施工会话。不要依赖其他聊天窗口的记忆；仓库文档和当前文件是唯一依据。

【仓库】
根目录：{{REPO_ROOT}}
项目：{{PROJECT_NAME}}
当前模块：{{MODULE_ID}} - {{MODULE_NAME}}

【本轮目标】
{{OBJECTIVE}}

【前置依赖】
{{DEPENDENCIES_AND_EVIDENCE}}

【必须遵守】
- 先读取 PROGRESS.md 的权威 YAML 区和 HARNESS.md 全局规则，再读取本模块 PRD 锚点、接口文档及范围内相关代码/测试。
- 不读取或复述无关聊天历史，不扫描/输出整个仓库，不倾倒完整日志；只取建立本模块上下文所需内容。
- 开工前核对模块状态、依赖和基线门禁。任一项与本提示词或仓库记录冲突，立即停止施工，在 PROGRESS.md 记录 blocker 并汇报冲突。
- 只修改允许范围；不做无关重构，不更改其他模块，不擅自改变已冻结接口。遇到范围外必要改动先记录并停止相关扩展。
- 不猜测缺失需求，不伪造测试结果，不跳过失败门禁。代码变更后必须重跑受影响验收。
- 一次只完成当前模块，不在本会话顺手开始下一模块。

【允许修改】
{{SCOPE_INCLUDE}}

【禁止修改】
{{SCOPE_EXCLUDE}}

【接口与已确认决定】
{{CONTRACTS_AND_DECISIONS}}

【验收命令】
{{ACCEPTANCE_COMMANDS}}

【执行步骤】
1. 确认仓库根目录，读取 PROGRESS.md、HARNESS.md 及上文指定的最少相关文件；检查 git status 和当前模块相关差异。
2. 用简短清单复述目标、边界、接口和验收方式；确认无冲突后，将本模块设为 IN_PROGRESS。
3. 实施当前模块，必要时先运行针对性测试；不加载无关文件或完整历史日志。
4. 运行全部模块验收命令，然后运行 `python tools/check_env.py`、`python runner.py check-env`、`python runner.py status` 和 `python runner.py verify`。记录实际命令、退出码、结果摘要和时间。
5. 仅当全部要求通过时，更新 PROGRESS.md：交付文件、证据、关键决定、下一可执行模块；将本模块置为 DONE。
6. 若任一门禁失败或无法运行，模块保持 IN_PROGRESS，workflow.state 设为 BLOCKED，写明错误、影响和具体重试步骤；不得生成“下一个模块已就绪”的交接。
7. 通过时，不要施工下一模块；生成并打印下一会话的完整接力提示词。若所有模块 DONE，改为执行最终全局验收并按 HARNESS.md 规则收尾。

【完成回复格式】
- 本模块状态：DONE 或 IN_PROGRESS（不得使用其他值）
- 变更文件：路径列表
- 验收证据：每条命令及真实退出码
- 关键结论/接口变化：没有则写“无”
- 阻塞与恢复步骤：没有则写“无”
- 下一步：下一模块提示词已生成，或当前模块阻塞，或进入最终验收
```

## 7. 建议验收清单

- 新项目未通过第 0 步门禁时，Skill 明确阻止功能施工。
- 模块依赖未完成时，调度器不发起该模块会话。
- 任一验收或全局门禁失败时，不会将模块置为 `DONE` 或调度下一模块。
- 手动模式输出含完整任务边界的下一会话提示词；自动模式只在真实可用的隔离子代理能力下启用。
- 代码后续修改会使相应旧验证证据失效；全部模块完成后必须执行最终全局验收。
