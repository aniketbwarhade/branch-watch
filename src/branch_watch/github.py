"""Small GitHub REST client used by the branch-watch Python CLI."""

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


class GitHubError(RuntimeError):
    pass


def token_from_environment() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Any:
        url = "https://api.github.com" + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "branch-watch",
                **({"Content-Type": "application/json"} if body else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise GitHubError("GitHub API {}: {}".format(error.code, detail)) from error
        except urllib.error.URLError as error:
            raise GitHubError("Could not reach GitHub: {}".format(error.reason)) from error

    def repository(self, repo: str) -> Dict[str, Any]:
        return self.request("/repos/" + repo)

    def branches(self, repo: str) -> List[Dict[str, Any]]:
        return self.request("/repos/{}/branches?per_page=100".format(repo))

    def compare(self, repo: str, base: str, head: str) -> Dict[str, Any]:
        path = "/repos/{}/compare/{}...{}".format(
            repo, urllib.parse.quote(base, safe=""), urllib.parse.quote(head, safe="")
        )
        return self.request(path)

    def branch_commit(self, repo: str, branch: str) -> Dict[str, Any]:
        path = "/repos/{}/branches/{}".format(
            repo, urllib.parse.quote(branch, safe="")
        )
        branch_data = self.request(path).get("commit", {})
        sha = branch_data.get("sha")
        if not sha:
            return branch_data
        return self.request(
            "/repos/{}/commits/{}".format(repo, urllib.parse.quote(sha, safe=""))
        )

    def deployments(self, repo: str) -> List[Dict[str, Any]]:
        return self.request("/repos/{}/deployments?environment=production&per_page=1".format(repo))

    def pulls(self, repo: str) -> List[Dict[str, Any]]:
        return self.request("/repos/{}/pulls?state=open&per_page=100&sort=created&direction=asc".format(repo))

    def create_pull(self, repo: str, title: str, head: str, base: str, body: str) -> Dict[str, Any]:
        return self.request(
            "/repos/{}/pulls".format(repo),
            method="POST",
            payload={"title": title, "head": head, "base": base, "body": body},
        )

    def all_forks(self, org: Optional[str] = None) -> List[Dict[str, Any]]:
        path = "/orgs/{}/repos?type=fork&per_page=100".format(org) if org else "/user/repos?type=fork&per_page=100"
        return self.request(path)


def parse_repo(repo: str) -> Tuple[str, str]:
    owner, separator, name = repo.partition("/")
    if not separator or not owner or not name:
        raise ValueError("Repo must be in 'owner/name' format")
    return owner, name
