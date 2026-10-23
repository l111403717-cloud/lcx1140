# Antigravity 宿主适配契约（子代理、工件与生命周期钩子）

本文档仅在 Antigravity（反重力）环境中使用。Codex 环境无需读取本文件。

## 1. 原生子代理（Subagent）隔离验收

在 Antigravity 中，任务分工与独立验收方式如下：
- **实施主体**：主代理（Parent Agent）负责规划、白名单圈定与核心业务代码编写。
- **独立验收裁判**：在 Tier 2 验收阶段，可派发只读子代理（如内置的 `research` 子代理）作为“独立裁判”。
  - 裁判子代理只具备只读与命令执行权限。
  - 裁判运行 `hx verify` / `git diff` 进行独立核验，主代理不自我宣称通过。

## 2. 工件系统（Artifacts）与单一事实源（SSOT）

Antigravity 拥有原生的 Artifact 渲染能力：
- **展示通道**：可以将 PLAN 和验收面板生成为 Markdown Artifact（位于 `<appDataDir>/brain/<conversation-id>/`），方便用户直观查看状态。
- **单一事实源约束**：工程的机器状态和持久交接计划仍必须严格以项目内的 `.harness/PLAN.md` 与 `.harness/state.json` 为准，Artifact 仅作为渲染视图，避免维护双重事实源。

## 3. 生命周期钩子（Lifecycle Hooks）硬拦截

Antigravity 原生支持 `~/.gemini/config/hooks.json`：
- **`PreToolUse` 硬拦截**：当模型调用 `write_file` 或 `edit_file` 时，自动触发 `hx guard` 拦截器：
  - 尝试篡改已被 SHA256 锁定的构建/配置/测试入口（如 `package.json`、`tsconfig.json`）时，直接返回 `deny` 阻断。
  - 尝试在项目根目录下生成临时 `.py` / `.sh` / `.mjs` 杂项脚本时，直接返回 `deny` 阻断。
  - 普通业务修改自动返回 `allow` 放行。
- **`Stop` 收尾审计**：在 Agent 执行结束时自动触发 `hx stop`，若工作区有修改则自动记录一次最新 diff 审计快照。
