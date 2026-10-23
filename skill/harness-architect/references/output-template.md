# 双轨交付物生成模板 (Output Templates)

当 Skill 完成访谈后，必须严格按照以下结构统一输出交付物。

---

## 交付物一：`PRD.md`（产品需求文档）

```markdown
# [项目名称] 产品需求文档 (PRD)

## 1. 产品概述与目标用户
- 核心解决痛点：
- 目标人群画像：

## 2. 核心功能与页面清单
- 页面 1：[功能描述、关键输入输出]
- 页面 2：...

## 3. 核心业务算法与数据字典
- 计算公式与边界值：
- 本地/数据库存储 Schema (数据模型)：

## 4. 视觉与交互风格规范 (Anti-AI Flavor)
- 布局特点（如极窄边框、特定微动效、字体层级）：
```

---

## 交付物二：`HARNESS.md`（开发控制规范与施工紧箍咒）

```markdown
# [项目名称] 开发控制层规范 (Development Harness)

## 1. 团队协作模式
- 模式：生成 - 审查模式 (Producer-Reviewer)
- 职责：主开发 (Coder)负责代码生成，质检器 (Verifier)负责运行脚本验收。
- 重试上限：最多 3 次，超额触发熔断并保留快照。

## 2. 物理环境与安全红线 (Hard Guardrails)
- 内存红线：低于 [阈值] GB 拒绝一切构建。
- 环境死锁：锁死指定运行时路径 [如 JDK 21]。

## 3. 受限工具接口清单 (Bounded Tools)
- `tools/check_env.py`：只读环境检测工具。
- `runner.py`：受控验证入口；只运行登记的验证计划。
- 项目登记的验证器（例如 `tools/verify.py`）：由 `runner.py verify` 调用。

## 4. 施工提示词 (供直接复制发给 DeepSeek / 编程 AI)
> 请扮演本项目的主程序员。必须严格遵守以下物理铁律：
> 1. 严禁直接调用终端执行未受限命令；
> 2. 每次改完代码必须通过 `runner.py verify`（或其登记的验证器）验货；
> 3. 必须通过 0 报错验证方可汇报完成。

## 5. Pipeline Relay（多会话模块接力）
- 调度模式：MANUAL（默认，人工打开新会话）或 AUTO（仅宿主提供隔离子代理和独立工作区时启用）。
- 唯一可信源：项目根目录 PROGRESS.md；环境门禁证据仍以 .harness/gate.json 为准。
- 默认一模块一新会话、串行施工；并行必须满足依赖无关、文件所有权不重叠、接口已冻结和工作区隔离。
- 模块状态只允许 TODO、IN_PROGRESS、DONE；失败写入 workflow.state=BLOCKED，不能把失败写成完成。

### 5.1 子代理/多会话分工矩阵

| 角色 | 会话范围 | 可写范围 | 必须交付 | 禁止事项 |
|---|---|---|---|---|
| Relay Dispatcher（接力调度器） | 项目全局 | PROGRESS.md、任务包和汇总证据 | 依赖图、当前模块、门禁证据、下一棒提示词 | 伪造退出码、绕过门禁 |
| Module Implementer（模块实施者） | 一个模块、一个新会话 | 当前模块允许范围 | 代码、测试结果、变更文件、决策、阻塞 | 改其他模块、扩大范围、顺手重构 |
| Verifier（验收者） | 当前模块或最终集成 | 仅授权的验证报告或修复文件 | 命令、退出码、断言、报告和失败摘要 | 只听口头描述、删除失败日志 |

主 PROGRESS.md 只能由调度器串行写入。实施者发现跨模块影响时返回报告，不直接修改邻接模块。

### 5.2 模块施工流水线

0. Environment Gate：创建/核验两个门禁工具，执行 python tools/check_env.py、python runner.py check-env、python runner.py status。
1. Architecture：生成 PRD.md、HARNESS.md 和 PROGRESS.md，拆分模块、依赖、范围、接口和验收命令。
2. Dispatch：选择依赖全部 DONE 的模块，冻结任务包和文件所有权，将模块置为 IN_PROGRESS。
3. Fresh Session：新会话按任务包只读必要文件，发现冲突先阻塞。
4. Module Verify：通过受控 Runner（运行器）执行登记的模块验收。
5. Relay Gate：重跑 check_env.py、runner.py check-env、runner.py status 和 runner.py verify，全部真实通过后记录证据并置 DONE。
6. Handoff：AUTO 启动下一个隔离子代理；MANUAL 打印完整接力提示词，不能假定新会话已启动。
7. Final Verify：所有模块 DONE 后执行完整验证和需求核对，最终状态置 COMPLETE。

### 5.3 防信息丢失任务包

每次委派必须携带 module_id、唯一目标、完成定义、依赖证据、PRD 锚点、接口约束、允许/禁止路径、验收命令和预期退出码、环境前提、未决问题、停止条件、回报格式以及主 PROGRESS.md 的唯一写入者。接棒会话必须先读 PROGRESS.md、HARNESS.md、PRD 指定章节和范围内相关文件；不得依赖旧聊天记录或全库倾倒。状态、接口、提示词冲突时停止施工并记录阻塞。

### 5.4 会话退出门禁

当前模块的所有登记验收命令、python tools/check_env.py、python runner.py check-env、python runner.py status、python runner.py verify 必须在最终文件状态下真实通过，并记录命令、退出码、时间和证据路径。任何失败、无法运行或证据过期都保持 IN_PROGRESS 并转 BLOCKED，不得调度下一模块。

### 5.5 接力提示词

使用 references/pipeline-relay.md 中的完整模板，将当前模块实际状态、依赖证据、允许/禁止路径、接口决定和验收命令填入后整段打印。门禁失败时只生成恢复当前模块的提示词。

## 6. PROGRESS.md（状态中继文件）

PROGRESS.md 必须包含 schema_version、workflow.state、workflow.mode、current_module、baseline_gate、final_gate，以及每个模块的 id、name、status、depends_on、objective、prd_refs、scope、contracts、acceptance、deliverables、evidence、decisions 和 blockers。完整 Schema 与提示词模板见 references/pipeline-relay.md。
```
