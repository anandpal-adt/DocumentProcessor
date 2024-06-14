from __future__ import annotations

from typing import TYPE_CHECKING, List

from predibase.resources.repo import Repo

if TYPE_CHECKING:
    from predibase import Predibase


class Repos:
    def __init__(self, client: Predibase):
        self._client = client

    def create(self, *, name: str, description: str | None = None, exists_ok: bool = False) -> Repo:
        resp = self._client.http_post(
            "/v2/repos",
            json={
                "name": name,
                "description": description,
                "existsOk": exists_ok,
            },
        )
        return Repo.model_validate(resp)

    def get(self, repo_ref: str | Repo) -> Repo:
        if isinstance(repo_ref, Repo):
            repo_ref = repo_ref.name

        return Repo.model_validate(self._client.http_get(f"/v2/repos/{repo_ref}"))

    def list(self, limit: int = 10) -> List[Repo]:
        resp = self._client.http_get(f"/v2/repos?limit={limit}")
        return [Repo.model_validate(r) for r in resp["data"]["repos"]]


