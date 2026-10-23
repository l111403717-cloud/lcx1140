# AI Harness (全局受控开发控制层)

跨平台（macOS / Linux）的通用 AI 编程安全与质量门禁系统，统一分发至 Codex (`~/.codex`) 与 Antigravity (`~/.gemini`)。

## 架构组成

- `gate/micro-gate.md`：轻量微契约，注入全局 `AGENTS.md` 与 `GEMINI.md`。
- `bin/hx`：确定性执行脚本（detect、lock、baseline、verify、audit、gc、handoff、map-check、guard、stop）。
- `skill/harness-architect/`：宿主无关的通用控制层 Skill，分级路由（Tier 0-2）。
- `skill/map/`：项目轻量架构地图与规范索引 Skill，注入首行保鲜锚点与防盲搜导航。
- `adapters/`：宿主专用适配器：
  - `codex/agents/harness-verifier.toml`：只读验收裁判代理。
  - `agy/hooks.json`：Antigravity 生命周期钩子（PreToolUse 硬拦截与 Stop 收尾审计）。

## 核心设计与防御机制

1. **确定性执行（hx）**：将哈希锁定、测试入口保护、diff 审计交由底层脚本执行，不占模型上下文 Token，避免运动员自任裁判。
2. **Fail-Open 设计说明（Guard 容错）**：
   - 当 `hx guard` 执行过程中 python3 解析或运行时发生异常时，出于不阻塞正常开发流程的考虑，采用 **Fail-Open（故障放行）** 策略，默认返回 `{"decision":"allow"}`。
   - 所有异常堆栈均会自动追加记录至 `~/.harness-locks/guard-error.log`，方便事后审计与排查。
3. **未跟踪文件放水审计**：
   - `hx audit` 不仅比对已跟踪文件的 Git Diff，还会自动扫描 `git ls-files --others` 列出的未跟踪新文件内容。
   - 若新建文件中包含 `.skip(`、`@ts-ignore`、`eslint-disable`、`|| true` 等放水语句，直接判定 `AUDIT FAIL`。
4. **孤儿锁目录清理（hx gc）**：
   - 运行 `hx gc` 可自动扫描并清除 `~/.harness-locks/` 下无对应仓库或临时测试遗留的孤儿锁目录。
5. **统一判级规则**：
   - 文件数量（≥3 文件）只决定是否加载 `harness-architect` 技能，不决定是否创建持久化 PLAN 或接力文件。一次做完且已验证的任务直接交付，不走形式主义交接。

## 地图与接力 (Map + Handoff)

### 1. 新增子命令
- `hx handoff`：自动提取改动文件、运行指纹与最新验证证据，生成或更新 `.harness/PLAN.md` 中的 `## Handoff` 接力块。
- `hx handoff --check`：下一位 Agent 开工前校验接力块有效性与指纹匹配度。
- `hx map-check`：校验项目根目录 `PROJECT_MAP.md` 的锚点有效性、路径存在性与结构变更量。

### 2. 退出码表
- **`hx handoff --check` 退出码**：
  | 退出码 | 输出格式 | 含义 |
  |---|---|---|
  | 0 | `FRESH` | 接力块完备且指纹与当前工作区一致，可直接接力 |
  | 1 | `STALE (handoff fp=X, current fp=Y)` | 代码在交接后被改动，需先跑 `hx verify` 刷新证据 |
  | 2 | `INCOMPLETE (TODO 数: N)` | 上一棒存在未填写的 `TODO(agent)` 占位符 |
  | 3 | `NO_HANDOFF` | 未找到 PLAN.md 或 HANDOFF 标记块 |

- **`hx map-check` 退出码**：
  | 退出码 | 输出格式 | 含义 |
  |---|---|---|
  | 0 | `FRESH (structural=N)` | 地图路径完备且结构变更在安全阈值内 |
  | 1 | `STALE (structural=N, missing=M)` | 地图中存在缺失路径，或变更文件数达到阈值 |
  | 2 | `NO_MAP` / `NO_ANCHOR` | 缺少地图文件或首行缺少锚点 Commit SHA |

### 3. 环境变量
- `HX_MAP_THRESHOLD`：结构变动触发地图过期的文件数阈值（默认为 `5`）。

## 安装与维护

```bash
# 执行安装或同步更新
~/ai-harness/install.sh
```
`install.sh` 具备严格的幂等性（Idempotency），可安全重复执行。
