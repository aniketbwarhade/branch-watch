"""Command-line interface for branch-watch."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from .dashboard import serve
from .github import GitHubClient, GitHubError, parse_repo, token_from_environment

CONFIG_PATH = Path.home() / ".branch-watch.toml"


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"ignore": [], "repos": []}
    try:
        import tomllib  # type: ignore
        with CONFIG_PATH.open("rb") as file:
            return tomllib.load(file)
    except ImportError:
        result: Dict[str, Any] = {"ignore": [], "repos": []}
        for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                continue
            value = value.strip()
            if key.strip() == "token":
                result["token"] = value.strip('"')
            elif key.strip() in ("ignore", "repos"):
                result[key.strip()] = [item.strip().strip('"') for item in value.strip("[]").split(",") if item.strip()]
        return result


def save_config(config: Dict[str, Any]) -> None:
    lines: List[str] = []
    if config.get("token"):
        lines.append('token = "{}"'.format(config["token"]))
    for key in ("ignore", "repos"):
        values = config.get(key, [])
        lines.append("{} = [{}]".format(key, ", ".join(json.dumps(value) for value in values)))
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_client() -> GitHubClient:
    config = load_config()
    token = config.get("token") or token_from_environment()
    if not token:
        raise RuntimeError("No GitHub token found. Set GITHUB_TOKEN, run `bw auth <token>`, or install gh and run `gh auth login`.")
    return GitHubClient(token)


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2))


def branches(client: GitHubClient, args: argparse.Namespace) -> None:
    parse_repo(args.repo)
    base = args.base or client.repository(args.repo).get("default_branch", "main")
    names = [item.get("name", "") for item in client.branches(args.repo) if item.get("name") != base]
    rows = []
    for name in names:
        comparison = client.compare(args.repo, base, name)
        rows.append({"branch": name, "base": base, "behind": comparison.get("behind_by", 0), "ahead": comparison.get("ahead_by", 0)})
    rows.sort(key=lambda row: (row["behind"], row["ahead"]), reverse=True)
    if args.behind_only:
        rows = [row for row in rows if row["behind"] > 0]
    if args.json:
        print_json(rows)
        return
    print("\n→ {} (base: {})\n".format(args.repo, base))
    for row in rows:
        if row["behind"] == 0 and row["ahead"] == 0:
            status = "✓ up to date"
        else:
            status = "↓ {} behind  ↑ {} ahead".format(row["behind"], row["ahead"])
        print("  {:<30}  {}".format(row["branch"], status))


def forks(client: GitHubClient, args: argparse.Namespace) -> None:
    ignored = set(load_config().get("ignore", []))
    rows = []
    for item in client.all_forks(args.org):
        repo = item.get("full_name", "")
        parent = item.get("parent") or {}
        upstream = parent.get("full_name")
        if not upstream or repo in ignored:
            continue
        base = parent.get("default_branch", "main")
        comparison = client.compare(repo, base, "HEAD")
        rows.append({"repo": repo, "upstream": upstream, "behind": comparison.get("behind_by", 0), "ahead": comparison.get("ahead_by", 0)})
    rows.sort(key=lambda row: (row["behind"], row["ahead"]), reverse=True)
    if args.behind_only:
        rows = [row for row in rows if row["behind"] > 0]
    if args.json:
        print_json(rows)
        return
    print("\nForked repositories\n")
    for row in rows:
        print("  {:<30} {:<30} ↓ {} behind  ↑ {} ahead".format(row["repo"], row["upstream"], row["behind"], row["ahead"]))


def prs(client: GitHubClient, args: argparse.Namespace) -> None:
    parse_repo(args.repo)
    rows = [{"number": item.get("number"), "title": item.get("title"), "author": (item.get("user") or {}).get("login"), "head": (item.get("head") or {}).get("ref"), "base": (item.get("base") or {}).get("ref"), "draft": item.get("draft"), "created_at": item.get("created_at")} for item in client.pulls(args.repo)]
    if args.json:
        print_json(rows)
        return
    print("\n→ {} — {} open PRs\n".format(args.repo, len(rows)))
    for row in rows:
        print("  #{}  {}".format(row["number"], row["title"]))
        print("       {} → {} by @{}".format(row["head"], row["base"], row["author"]))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bw", description="Track branch and fork sync status on GitHub")
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("auth", help="Save your GitHub personal access token")
    auth.add_argument("token")
    dashboard = commands.add_parser("dashboard", help="Open the multi-repository release dashboard")
    dashboard.add_argument("--repo", dest="repos", action="append", default=[])
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8787)
    dashboard.add_argument("--release-branch", help="Release branch name when it is not release or release/*")
    branch = commands.add_parser("branches", help="Show branch sync status")
    branch.add_argument("repo"); branch.add_argument("--behind-only", action="store_true"); branch.add_argument("--json", action="store_true"); branch.add_argument("--base")
    fork = commands.add_parser("forks", help="Show fork sync status")
    fork.add_argument("--behind-only", action="store_true"); fork.add_argument("--json", action="store_true"); fork.add_argument("--org")
    pr = commands.add_parser("prs", help="List open pull requests")
    pr.add_argument("repo"); pr.add_argument("--json", action="store_true")
    ignore = commands.add_parser("ignore", help="Manage ignored repositories")
    ignore.add_argument("action", choices=["add", "remove", "list"]); ignore.add_argument("repo", nargs="?")
    return parser


def main() -> None:
    args = make_parser().parse_args()
    try:
        if args.command == "auth":
            config = load_config(); config["token"] = args.token; save_config(config); print("Token saved.")
        elif args.command == "ignore":
            config = load_config(); values = config.setdefault("ignore", [])
            if args.action == "list": print("\n".join(values) if values else "Ignore list is empty.")
            elif not args.repo: raise RuntimeError("ignore add/remove requires owner/name")
            elif args.action == "add":
                if args.repo not in values: values.append(args.repo); save_config(config)
                print("Added '{}' to ignore list.".format(args.repo))
            else:
                if args.repo in values: values.remove(args.repo); save_config(config)
                print("Removed '{}' from ignore list.".format(args.repo))
        else:
            client = build_client()
            if args.command == "dashboard":
                repos = args.repos or load_config().get("repos", [])
                if not repos: raise RuntimeError("Use --repo owner/name or add repos to ~/.branch-watch.toml")
                serve(client, repos, args.host, args.port, args.release_branch)
            elif args.command == "branches": branches(client, args)
            elif args.command == "forks": forks(client, args)
            elif args.command == "prs": prs(client, args)
    except (GitHubError, RuntimeError, ValueError) as error:
        raise SystemExit("Error: {}".format(error))


if __name__ == "__main__":
    main()
