#!/usr/bin/env bash
# 下载 GitLab 公开手册的 people-group / security / finance / legal 四个部门目录，作为基准的真实背景语料。
# 语料为 CC BY-SA 4.0，不随仓库分发；默认下载到仓库外的 ./.corpus/handbook。
set -euo pipefail
dest="${1:-.corpus/handbook}"
mkdir -p "$(dirname "$dest")"
git clone -q --depth 1 --filter=blob:none --sparse https://gitlab.com/gitlab-com/content-sites/handbook.git "$dest.git"
git -C "$dest.git" sparse-checkout set content/handbook/people-group content/handbook/security content/handbook/finance content/handbook/legal
rm -rf "$dest" && mv "$dest.git/content/handbook" "$dest" && rm -rf "$dest.git"
echo "已下载 $(find "$dest" -name '*.md' | wc -l) 篇到 $dest"
