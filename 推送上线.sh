#!/usr/bin/env bash
# 把本地仓库推到 GitHub，并给出后续要点的几步
# 用法：bash 推送上线.sh 你的GitHub用户名
set -euo pipefail

OWNER="${1:-}"
REPO="${2:-history-textbook-index}"

if [ -z "$OWNER" ]; then
  echo "用法: bash 推送上线.sh 你的GitHub用户名 [仓库名]"
  echo "例:   bash 推送上线.sh 495241318-afk"
  exit 1
fi

echo "→ 检查本地状态"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "当前目录不是 git 仓库"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
  echo "有未提交的改动，先提交再推送："
  git status --short
  exit 1
fi

echo "→ 设置远程地址"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${OWNER}/${REPO}.git"

echo "→ 推送 main 分支"
git push -u origin main

cat <<EOF

✅ 推送完成：https://github.com/${OWNER}/${REPO}

接下来在网页上点三处：

1. Settings → Pages → Source 选「GitHub Actions」
2. Actions 标签页，等「构建索引并发布」跑完（第一次约 1 分钟）
3. 回到 Settings → Pages，顶部会显示站点地址：
   https://${OWNER}.github.io/${REPO}/

之后每次 git push，网页会自动更新，不用手动构建。
EOF
