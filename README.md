# AI Harness (全局受控开发控制层)

跨平台（macOS / Linux）的通用 AI 编程安全与质量门禁系统，统一分发至 Codex (`~/.codex`) 与 Antigravity (`~/.gemini`)。

## 架构组成

- `gate/micro-gate.md`：13 行轻量微契约，注入全局 `AGENTS.md` 与 `GEMINI.md`。
- `bin/hx`：确定性执行脚本（detect、lock、baseline、verify、audit、gc、guard、stop）。
- `skill/harness-architect/`：宿主无关的通用控制层 Skill，分级路由（Tier 0-2）。
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

## 安装与维护

```bash
# 执行安装或同步更新
~/ai-harness/install.sh
```
`install.sh` 具备严格的幂等性（Idempotency），可安全重复执行。
