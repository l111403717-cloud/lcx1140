# Tier 2 多模块接力与流水线施工规范 (Pipeline Relay)

## 1. 适用范围
本规范仅适用于 **Tier 2** 复杂多模块架构变更，或用户明确要求“多会话分模块接力施工”的场景。
普通任务遵循轻量敏捷流程，不启用本协议，更不强制创建模块拆解表格。
任何单会话可闭环的日常改动，严禁引入多模块接力流。

## 2. 唯一事实源（SSOT）
接力期间唯一的计划与状态文件为 `.harness/PLAN.md`。必须包含且仅包含以下 3 个固定段落：
1. `## Goal & Non-Goals`：明确交付目标与禁止触碰边界。
2. `## Modules`：模块分解表，格式如下：
   | ID | 模块名称 | 范围白名单 | 状态 (TODO / IN_PROGRESS / DONE) | 验收命令 |
   |---|---|---|---|---|
   | M1 | 用户认证改造 | `src/auth/*` | DONE | `npm run test` |
   | M2 | 权限中间件 | `src/middleware/*` | IN_PROGRESS | `npm run test` |
3. `<!-- HANDOFF BEGIN -->` ... `<!-- HANDOFF END -->`：由 `hx handoff` 生成并维护的标准接力块。机器状态如需记录可放 `.harness/state.json`。

## 3. 模块出口门禁
只有同时满足以下两条，当前推进的模块状态才允许从 `IN_PROGRESS` 变为 `DONE`：
1. 当前模块所需验收实际完成，`hx verify` 输出 `RESULT PASS` 且退出码为 0；历史失败仍为失败，quick 未跑项、仅审计与检查不完整不能豁免；
2. 运行 `hx handoff --check` 退出码为 0，输出 `FRESH`，并另行确认 `VERIFICATION PASS`。FRESH 只证明交接匹配。
未满足时保持 `IN_PROGRESS`，并在 Handoff 段的“④ 未完成 / 风险”中如实写明阻塞原因。

## 4. 施工纪律
1. **一次只推进一个模块**：严禁在一个会话或交接时顺手修改多个未锁定模块。
2. **AUTO 与 MANUAL 模式**：
   - 宿主支持隔离子代理时（如 Antigravity 子代理或 Codex spawn_agent），可设为 AUTO，由主代理统一维护 PLAN.md；
   - 否则为 MANUAL，必须在会话结束时打印出可复制的接力 Prompt，由用户新开会话，严禁虚假宣称“已自动清空上下文”。
3. **并行写入隔离**：子代理之间文件写入白名单绝对不能重叠。公共接口与配置由主代理串行修改。需物理文件隔离时使用独立工作区：`git worktree add .harness/wt/<模块ID>`。

## 5. 标准接力 Prompt 模板
新开会话或跨模型交接时，输出以下格式的接力指令：
```markdown
> 项目路径：<ROOT>
> 1. 先运行 `hx handoff --check`，确认状态为 FRESH；
> 2. 当前推进模块：<模块ID>（写入白名单：<文件列表>）；
> 3. 接力第一步：<直接执行的具体动作与命令>；
```
## 6. 状态流转约束
- 严禁擅自修改已锁定模块的完成状态。
- 接力过程以代码实际 diff 为准，任何口头声明必须经由 `hx verify` 与 `hx handoff --check` 双重校验通过。

