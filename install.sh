#!/usr/bin/env bash
set -euo pipefail

H="$HOME/ai-harness"

link(){
  mkdir -p "$(dirname "$2")"
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    echo "备份已有非链接目标: $2 -> $2.pre-harness"
    mv "$2" "$2.pre-harness"
  fi
  ln -sfn "$1" "$2"
  echo "软链接: $2 -> $1"
}

inject(){
  local f="$1"
  touch "$f"
  local tmp
  tmp=$(mktemp)
  python3 -c '
import sys, re
c = open(sys.argv[1]).read()
cleaned = re.sub(r"\n*<!-- HARNESS-GATE BEGIN[\s\S]*?<!-- HARNESS-GATE END -->", "", c).rstrip()
print(cleaned)
' "$f" > "$tmp"
  {
    cat "$tmp"
    echo ""
    echo ""
    cat "$H/gate/micro-gate.md"
  } > "$f"
  rm -f "$tmp"
  echo "门禁微契约已注入: $f"
}

echo "=== 开始安装 Harness 全局集成 ==="

# 1. 链接 Skill 目录
link "$H/skill/harness-architect" "$HOME/.codex/skills/harness-architect"
link "$H/skill/harness-architect" "$HOME/.gemini/config/skills/harness-architect"
link "$H/skill/map" "$HOME/.codex/skills/map"
link "$H/skill/map" "$HOME/.gemini/config/skills/map"

# 2. 链接 Codex 裁判代理与 Antigravity 钩子
link "$H/adapters/codex/agents/harness-verifier.toml" "$HOME/.codex/agents/harness-verifier.toml"
link "$H/adapters/agy/hooks.json" "$HOME/.gemini/config/hooks.json"

# 3. 链接 hx 可执行脚本到用户 PATH
mkdir -p "$HOME/.local/bin"
ln -sfn "$H/bin/hx" "$HOME/.local/bin/hx"
echo "已链接 hx 到 $HOME/.local/bin/hx"
ln -sfn "$H/bin/hx" /usr/local/bin/hx 2>/dev/null || true

# 4. 注入全局微契约（保留用户原有其他规则，去除累积空行）
inject "$HOME/.codex/AGENTS.md"
inject "$HOME/.gemini/GEMINI.md"

# 5. 配置全局 gitignore，防止 .harness 污染项目代码
GI="${XDG_CONFIG_HOME:-$HOME/.config}/git/ignore"
mkdir -p "$(dirname "$GI")"
touch "$GI"
if ! grep -qx '\.harness/' "$GI" 2>/dev/null; then
  echo '.harness/' >> "$GI"
  echo "已将 .harness/ 写入全局 gitignore ($GI)"
fi
git config --global core.excludesfile "$GI" 2>/dev/null || true

echo "=== Harness 全局集成安装完成 ==="
