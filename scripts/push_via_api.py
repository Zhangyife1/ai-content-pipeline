"""通过 GitHub Git Database API 推送仓库（不依赖 github.com 直连）。

适用场景：本机网络可访问 api.github.com，但 github.com 被阻断，无法直接 git push。
实现：完整走一遍 Git 底层对象上传（blobs -> trees -> commits -> refs），
并处理“空仓库无法直接创建 blob”的问题（先以空树引导第一个 ref）。

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
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
PUSH_STATE_FILE = Path("data") / "pushed_refs.json"


def git(args: list[str]) -> bytes:
    return subprocess.check_output(["git"] + args)


def git_text(args: list[str]) -> str:
    return git(args).decode("utf-8", errors="replace").strip()


def curl_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list | None]:
    """返回 (HTTP 状态码, 解析后的 JSON)。"""
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
        "-w",
        "\n__HTTP_CODE__%{http_code}",
        "--max-time",
        "90",
    ]
    data_bytes = b""
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        cmd += ["--data-binary", "@-"]
    proc = subprocess.run(cmd, input=data_bytes, capture_output=True)
    out = proc.stdout.decode("utf-8", errors="replace")
    code = 0
    body = out
    if "__HTTP_CODE__" in out:
        body, _, marker = out.rpartition("__HTTP_CODE__")
        try:
            code = int(marker.strip())
        except ValueError:
            code = 0
    try:
        parsed = json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return code, parsed


def repo_path(path: str) -> str:
    return f"/repos/{OWNER}/{REPO}{path}"


def collect_local_objects() -> tuple[str, dict[str, list[dict]], list[str], list[str]]:
    """返回 (head, trees, blobs, commits 顺序 oldest->newest)。"""
    head = git_text(["rev-parse", "HEAD"])
    commits = git_text(["rev-list", "--reverse", head]).splitlines()
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

    root_trees = {git_text(["rev-parse", f"{commit}^{{tree}}"]) for commit in commits}
    for root in root_trees:
        walk(root)
    return head, trees, list(dict.fromkeys(blobs)), commits


def dry_run() -> int:
    head, trees, blobs, commits = collect_local_objects()
    print(f"HEAD: {head}")
    print(f"commits: {len(commits)}  trees: {len(trees)}  blobs: {len(blobs)}")
    print(f"tree entries: {sum(len(e) for e in trees.values())}")
    print("dry-run OK（未调用网络）")
    return 0


def load_push_state() -> dict:
    if PUSH_STATE_FILE.exists():
        try:
            return json.loads(PUSH_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"commits": {}, "blobs": [], "head": None, "remote_head": None}


def save_push_state(commit_map: dict[str, str], blob_shas: list[str], local_head: str, remote_head: str) -> None:
    state = load_push_state()
    state["commits"].update(commit_map)
    state["blobs"] = sorted(set(state.get("blobs", [])) | set(blob_shas))
    state["head"] = local_head
    state["remote_head"] = remote_head
    PUSH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUSH_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_repo(token_ok: bool) -> tuple[bool, str]:
    """创建仓库（若不存在）。返回 (created_now, repo_full_name)。"""
    code, data = curl_json(
        "POST",
        "/user/repos",
        {
            "name": REPO,
            "description": (
                "AI 内容生产管线：热点抓取 / RAG 生成 / 三层质检 / 人工审核 / "
                "多渠道发布 / RAG 客服 / GEO 工程化"
            ),
            "private": False,
        },
    )
    if code == 201:
        print(f"  仓库已创建: {OWNER}/{REPO}")
        return True, f"{OWNER}/{REPO}"
    if code == 422:
        print(f"  仓库已存在: {OWNER}/{REPO}")
        return False, f"{OWNER}/{REPO}"
    print(f"  创建仓库失败: HTTP {code} {json.dumps(data, ensure_ascii=False)[:300]}", file=sys.stderr)
    raise SystemExit(3)


def bootstrap_empty_repo() -> str:
    """空仓库无法通过 Git Database API 创建首个 commit（409）。

    改用 Contents API 写入占位 README：GitHub 会自动创建首个提交与 main 分支，
    之后 Git Database API 即可正常使用。
    """
    placeholder = b"# ai-content-pipeline\n\nBootstrap commit for API push.\n"
    code, data = curl_json(
        "PUT",
        f"/repos/{OWNER}/{REPO}/contents/README.md",
        {
            "message": "chore: bootstrap repository",
            "content": base64.b64encode(placeholder).decode("ascii"),
        },
    )
    if code != 201 or not isinstance(data, dict) or "commit" not in data:
        print(f"  引导 README 失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
        raise SystemExit(4)
    bootstrap_sha = data["commit"]["sha"]
    print(f"  已引导空仓库 refs/heads/{BRANCH}: {bootstrap_sha}")
    return bootstrap_sha


def push(force: bool = False) -> int:
    if not os.environ.get("GITHUB_TOKEN"):
        print("缺少 GITHUB_TOKEN 环境变量", file=sys.stderr)
        return 2

    print(f"[1/6] 创建/确认仓库 {OWNER}/{REPO}")
    created_now, _ = ensure_repo(True)

    bootstrap_sha: str | None = None
    code, ref_data = curl_json("GET", repo_path(f"/git/refs/heads/{BRANCH}"))
    if code == 200 and isinstance(ref_data, dict):
        bootstrap_sha = ref_data.get("object", {}).get("sha")
        print(f"[2/6] 远端已有分支，将本地历史作为其子提交（快进推送）")
    elif code in (404, 409):
        print(f"[2/6] 仓库为空，先引导 {BRANCH} 分支")
        bootstrap_sha = bootstrap_empty_repo()
    else:
        print(f"  检查分支失败: HTTP {code}", file=sys.stderr)
        return 6

    head, trees, blob_shas, commits = collect_local_objects()
    state = load_push_state()
    known_commits = state.get("commits", {})
    if state.get("head") == head and state.get("remote_head"):
        print("  本地 HEAD 已推送，无需更新。")
        return 0
    base_commit = state.get("head")
    if base_commit:
        commits = git_text(["rev-list", "--reverse", f"{base_commit}..HEAD"]).splitlines()
        # 重新收集增量提交涉及的对象
        trees = {}
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

        for c in commits:
            walk(git_text(["rev-parse", f"{c}^{{tree}}"]))
        blob_shas = list(dict.fromkeys(blobs))
    print(f"[3/6] 上传 blobs（{len(blob_shas)} 个）")
    known_blobs = set(state.get("blobs", []))
    blob_shas = [sha for sha in blob_shas if sha not in known_blobs]
    if not blob_shas:
        print("  无新增 blob")
    # Git 内容寻址：远端 blob SHA 与本地一致，已知对象可直接映射
    blob_map: dict[str, str] = {sha: sha for sha in known_blobs}
    for i, sha in enumerate(blob_shas, 1):
        content = git(["cat-file", "blob", sha])
        b64 = base64.b64encode(content).decode("ascii")
        code, data = curl_json("POST", repo_path("/git/blobs"), {"content": b64, "encoding": "base64"})
        if code != 201 or not isinstance(data, dict) or "sha" not in data:
            print(f"  blob 上传失败: {sha} HTTP {code} {str(data)[:200]}", file=sys.stderr)
            return 8
        blob_map[sha] = data["sha"]
        if i % 10 == 0:
            print(f"  ... {i}/{len(blob_shas)}")

    print("[4/6] 创建 trees")
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
        code, data = curl_json("POST", repo_path("/git/trees"), {"tree": entries})
        if code != 201 or not isinstance(data, dict) or "sha" not in data:
            print(f"  tree 创建失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
            raise SystemExit(9)
        tree_map[tree_sha] = data["sha"]
        return data["sha"]

    print("[5/6] 按顺序创建 commits")
    commit_map: dict[str, str] = {}
    for local_sha in commits:
        if local_sha in known_commits:
            commit_map[local_sha] = known_commits[local_sha]
            continue
        tree_sha = git_text(["rev-parse", f"{local_sha}^{{tree}}"])
        remote_tree = create_tree(tree_sha)
        message = git_text(["log", "-1", "--pretty=%B", local_sha])
        parent_shas = git_text(["log", "-1", "--pretty=%P", local_sha]).split()
        parents = []
        for parent in parent_shas:
            if parent in commit_map:
                parents.append(commit_map[parent])
            elif parent in known_commits:
                parents.append(known_commits[parent])
        if not parents and bootstrap_sha:
            parents = [bootstrap_sha]
        payload: dict = {"message": message, "tree": remote_tree}
        if parents:
            payload["parents"] = parents
        code, data = curl_json("POST", repo_path("/git/commits"), payload)
        if code != 201 or not isinstance(data, dict) or "sha" not in data:
            print(f"  commit 创建失败: {local_sha} HTTP {code} {str(data)[:200]}", file=sys.stderr)
            return 10
        commit_map[local_sha] = data["sha"]
        print(f"  {local_sha[:8]} -> {data['sha'][:8]} ({message.splitlines()[0][:50]})")

    final_sha = commit_map[head]
    save_push_state(commit_map, blob_shas + list(known_blobs), head, final_sha)
    print(f"[6/6] 更新分支 refs/heads/{BRANCH}")
    code, data = curl_json("PATCH", repo_path(f"/git/refs/heads/{BRANCH}"), {"sha": final_sha, "force": force})
    if code != 200:
        print(f"  ref 更新失败: HTTP {code} {str(data)[:200]}", file=sys.stderr)
        return 11

    print(f"推送完成: https://github.com/{OWNER}/{REPO}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="仅本地预检，不调用网络")
    parser.add_argument("--force", action="store_true", help="允许更新已存在的分支（仅用于确认由本脚本创建的仓库）")
    args = parser.parse_args()
    return dry_run() if args.dry_run else push(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
