"""通过 GitHub Git Database API 推送仓库（不依赖 github.com 直连）。

适用场景：本机网络可访问 api.github.com，但 github.com 被阻断，无法直接 git push。

用法：
    $env:GITHUB_TOKEN="ghp_xxx"          # 经典 PAT，需要 repo 权限（可创建仓库）
    python scripts/push_via_api.py --dry-run   # 仅本地预检，不调用网络
    python scripts/push_via_api.py             # 创建仓库并推送

注意：脚本不会打印 Token；日志只输出 HTTP 状态与仓库 URL。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://api.github.com"
OWNER = os.environ.get("GITHUB_OWNER", "Zhangyife1")
REPO = os.environ.get("GITHUB_REPO", "ai-content-pipeline")
CURL = os.environ.get("CURL_BIN", "curl.exe")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def git(args: list[str]) -> bytes:
    return subprocess.check_output(["git"] + args)


def git_text(args: list[str]) -> str:
    return git(args).decode("utf-8", errors="replace").strip()


def curl_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list | None]:
    cmd = [
        CURL,
        "-sS",
        "-X",
        method,
        f"{API_BASE}{path}",
        "-H",
        f"Authorization: Bearer {os.environ['GITHUB_TOKEN']}",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "Content-Type: application/json",
        "--max-time",
        "90",
    ]
    data_bytes = b""
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        cmd += ["--data-binary", "@-"]
    proc = subprocess.run(cmd, input=data_bytes, capture_output=True)
    body = proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(body) if body else None
    except json.JSONDecodeError:
        parsed = None
    return proc.returncode, parsed


def collect_local_objects() -> tuple[str, dict[str, list[dict]], list[str]]:
    """遍历本地 git 树，返回 (head_sha, {tree_sha: entries}, blob_sha 列表)。"""
    head = git_text(["rev-parse", "HEAD"])
    trees: dict[str, list[dict]] = {}
    blobs: list[str] = []

    def walk(tree_sha: str) -> None:
        if tree_sha in trees:
            return
        lines = git_text(["ls-tree", tree_sha])
        entries: list[dict] = []
        for line in lines.splitlines():
            meta, path = line.split("\t", 1)
            mode, obj_type, sha = meta.split(" ")
            entries.append({"mode": mode, "type": obj_type, "sha": sha, "path": path})
            if obj_type == "tree":
                walk(sha)
            else:
                blobs.append(sha)
        trees[tree_sha] = entries

    walk(git_text(["rev-parse", f"{head}^{{tree}}"]))
    return head, trees, list(dict.fromkeys(blobs))


def dry_run() -> int:
    head, trees, blobs = collect_local_objects()
    print(f"HEAD: {head}")
    print(f"trees: {len(trees)}  blobs: {len(blobs)}")
    total = sum(len(entries) for entries in trees.values())
    print(f"tree entries: {total}")
    print("dry-run OK（未调用网络）")
    return 0


def push() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量", file=sys.stderr)
        return 2

    print(f"[1/5] 创建/确认仓库 {OWNER}/{REPO}")
    code, data = curl_json(
        "POST",
        "/user/repos",
        {"name": REPO, "description": "AI 内容生产管线：热点抓取 / RAG 生成 / 三层质检 / 人工审核 / 多渠道发布 / RAG 客服 / GEO 工程化", "private": False},
    )
    if code not in (0, 201):
        if isinstance(data, dict) and "already_exists" in json.dumps(data):
            print("  仓库已存在")
        else:
            print(f"  创建仓库失败: HTTP {code} {json.dumps(data, ensure_ascii=False)[:300]}", file=sys.stderr)
            return 3

    head, trees, blob_shas = collect_local_objects()
    print(f"[2/5] 上传 blobs（{len(blob_shas)} 个）")
    blob_map: dict[str, str] = {}
    for i, sha in enumerate(blob_shas, 1):
        content = git(["cat-file", "blob", sha])
        b64 = base64.b64encode(content).decode("ascii")
        code, data = curl_json("POST", "/git/blobs", {"content": b64, "encoding": "base64"})
        if code not in (0, 201) or not isinstance(data, dict) or "sha" not in data:
            print(f"  blob 上传失败: {sha} HTTP {code} {str(data)[:200]}", file=sys.stderr)
            return 4
        blob_map[sha] = data["sha"]
        if i % 10 == 0:
            print(f"  ... {i}/{len(blob_shas)}")

    print("[3/5] 创建 trees")
    tree_map: dict[str, str] = {}

    def create_tree(tree_sha: str) -> str:
        if tree_sha in tree_map:
            return tree_map[tree_sha]
        entries = []
        for entry in trees[tree_sha]:
            if entry["type"] == "tree":
                child = create_tree(entry["sha"])
                entries.append({"path": entry["path"], "mode": entry["mode"], "type": "tree", "sha": child})
            else:
                entries.append({"path": entry["path"], "mode": entry["mode"], "type": "blob", "sha": blob_map[entry["sha"]]})
        code, data = curl_json("POST", "/git/trees", {"tree": entries})
        if code not in (0, 201) or not isinstance(data, dict) or "sha" not in data:
            print(f"  tree 创建失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
            raise SystemExit(5)
        tree_map[tree_sha] = data["sha"]
        return data["sha"]

    root_tree_remote = create_tree(git_text(["rev-parse", f"{head}^{{tree}}"]))

    print("[4/5] 创建 commit")
    commit_payload: dict = {
        "message": git_text(["log", "-1", "--pretty=%B"]).strip(),
        "tree": root_tree_remote,
    }
    parents = git_text(["log", "-1", "--pretty=%P"]).split()
    if parents:
        commit_payload["parents"] = parents
    code, data = curl_json("POST", "/git/commits", commit_payload)
    if code not in (0, 201) or not isinstance(data, dict) or "sha" not in data:
        print(f"  commit 创建失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
        return 6
    commit_sha = data["sha"]
    print(f"  commit: {commit_sha}")

    print("[5/5] 更新分支 ref")
    code, data = curl_json("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": commit_sha, "force": False})
    if code not in (0, 200):
        code, data = curl_json("POST", "/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit_sha})
        if code not in (0, 201):
            print(f"  ref 更新失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
            return 7

    print(f"推送完成: https://github.com/{OWNER}/{REPO}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="仅本地预检，不调用网络")
    args = parser.parse_args()
    return dry_run() if args.dry_run else push()


if __name__ == "__main__":
    sys.exit(main())
