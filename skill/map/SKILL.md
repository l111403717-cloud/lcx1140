---
name: map
description: 为任意项目快速构建轻量架构地图与规范索引（Architecture Map & Guide），生成 PROJECT_MAP.md 与 AGENTS.md/CLAUDE.md。防止后续开发中 AI 盲目全盘扫描代码。当用户输入 /map、提到“项目地图”、“建地图”、“做个地图”、“帮我把项目摸透”、“onboard”时触发。
metadata:
  origin: ECC / codebase-onboarding
---

# 项目全局架构地图建图技能 (Map)

系统性分析代码仓库，提炼结构化项目地图与规范索引，彻底杜绝 AI 每次接手项目时盲目全盘搜索。

## 适用场景 (When to Use)

- 用户说“建个地图”、“做个项目地图”、“/map”、“帮我把项目摸透”
- 用户说“给项目做个项目地图，方便 agent 改代码不用全看”
- 初次接手新项目，需要为 Agent 生成常驻架构索引与规范约束

## 核心法则 (Core Rules)

1. **绝对禁止全盘盲读**：严禁无脑 Read 每一个文件。只做前2级目录探测、配置文件抓取与关键入口（Entry Points）定位。
2. **轻量与高密度**：产出简洁、模块职责清晰的地图文档，确保后续 Agent 在 10 秒内了解整体架构并定位目标单文件。
3. **闭环双产出**：
   - 产出 1：`PROJECT_MAP.md`（项目架构地图、模块依赖表、目录职责、常见任务命令）
   - 产出 2：`AGENTS.md`（或增强 `CLAUDE.md`，规范后续 AI 修改代码前优先查阅地图，严禁全盘盲搜）
4. **与 harness-architect 强联动**：
   - 地图是 harness-architect 第 7 节的导航数据源；Tier 0 不因缺少地图而强制建图。
5. **增量保鲜模式**：
   - 地图已存在且 `hx map-check` 报 `STALE` 时，只更新受影响的段落，并刷新首行锚点 SHA；没有用户明确要求时不全量重建整张地图。

---

## 执行流水线 (Execution Workflow)

### 阶段 1：快速侦察（不读全量代码）
并行排查项目关键标识：
1. **包与依赖清单**：`package.json`, `requirements.txt`, `go.mod`, `Cargo.toml`, `pom.xml` 等；
2. **框架与运行时**：Vite, Next.js, Vue, React, Express/Fastify/Node, Spring, Django, FastAPI 等；
3. **核心入口**：`main.*`, `index.*`, `server.*`, `app.*`, `src/`；
4. **排除噪音目录**：自动忽略 `node_modules`, `.git`, `dist`, `build`, `__pycache__`, `.next`, 缓存及静态大文件。

### 阶段 2：梳理架构与目录索引
- **技术栈定义**：核心语言、主流框架、数据存储、打包工具。
- **模块职责映射（Where to Look）**：
  将前两级核心目录与文件逐一映射到业务功能（如：“用户认证在 `/auth`”、“UI基座在 `MainLayout.html`”、“接口代理在 `server.mjs`”）。
- **关键数据流与入口**：梳理一个请求或事件从触发到完成的核心流转路径。

### 阶段 3：落地规范与地图文件

#### 产出 1：在项目根目录写入 `PROJECT_MAP.md`
- **首行锚点**：第一行必须是 `<!-- map-commit: <git rev-parse HEAD 的完整 SHA> -->`（非 git 仓库写 `<!-- map-commit: none -->`）。
- 项目核心概述与架构图（Mermaid 或 ASCII）
- 核心文件清单表（文件路径、职责、强依赖、修改红线）
- 常用运维与启动命令
- 常见修改场景的快速定位表（如：“我要改某个功能，应该看哪几个文件”）

#### 产出 2：在项目根目录写入/更新 `AGENTS.md` (或 `CLAUDE.md`)
写入时只替换 `MAP-GUIDE` 标记块内部，保留项目 AGENTS.md 的其他内容；文件不存在就新建：
```markdown
<!-- MAP-GUIDE BEGIN -->
## 项目导航
1. 修改代码前先查 `PROJECT_MAP.md` 定位目标文件；纯问答/只读分析不强制。
2. 禁止全盘扫描；地图未覆盖的部分再做定点搜索。
3. 若存在 `.harness/PLAN.md`，先读其中的 Handoff 段（可用 `hx handoff --check` 校验是否过期）。
4. 怀疑地图过期时运行 `hx map-check`。
<!-- MAP-GUIDE END -->
```

---

## 示例产出格式 (PROJECT_MAP.md 范例)

```markdown
<!-- map-commit: 0123456789abcdef0123456789abcdef01234567 -->
# 项目架构全景地图 (PROJECT_MAP.md)

## 一、 系统架构与数据流
[简要说明项目运行机制]

## 二、 核心文件与模块索引 (FRAS)
| 文件路径 | 模块分类 | 核心职责 | 强依赖 | 避坑红线 |
| :--- | :--- | :--- | :--- | :--- |
| `src/server.mjs` | 服务入口 | 监听路由并启动服务 | Express | 不要更改端口配置 |

## 三、 快速定位导航 (Where to Look)
| 我想要修改/新增... | 对应目标文件 |
| :--- | :--- |
| 界面布局/菜单 | `src/views/Layout.vue` |
| 接口/服务端代理 | `src/server.mjs` |
| 数据库/模型 | `src/models/user.js` |
```
