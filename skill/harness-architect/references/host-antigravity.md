# Antigravity 宿主适配契约（子代理、工件与生命周期钩子）

本文档仅在 Antigravity（反重力）环境中使用。Codex 环境无需读取本文件。

## 1. 原生子代理（Subagent）隔离验收

在 Antigravity 中，任务分工与独立验收方式如下：
- **实施主体**：主代理（Parent Agent）负责规划、白名单圈定与核心业务代码编写。
- **独立验收裁判**：在 Tier 2 验收阶段，可派发只读子代理（如内置的 `research` 子代理）作为“独立裁判”。
  - 裁判子代理只具备只读与命令执行权限。
  - 裁判按验收范围运行相关检查、核对实际差异，确认有效的证据可复用；依据真实结果报告，不凭口头声明通过。
  - 普通小改和静态上传沿用全局轻量约定，不因宿主不同默认派发裁判或重跑完整回归。

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
- **`Stop` 收尾审计**：在工作区路径已知时运行范围审计，包含暂存和未跟踪改动；在 `last-audit.json/.txt` 分别记录 AUDIT 与 VERIFICATION。响应 `{}`/退出 0 仅表示通知完成，不是功能通过；Git 错误保留为 INCOMPLETE。
- 钩子与普通 hx 使用同一 `HX_STATE_HOME` 和项目根；FRESH 不等于验证 PASS，未执行或不完整不能被宿主改写为通过。没有完整验证不阻止普通业务写入，锁变更复用已取得的授权。
