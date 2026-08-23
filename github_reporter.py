"""
GitHub-Reporter: создаёт Issue в GITHUB_REPO по устаревшему разделу
документации (stale binding) через PyGithub.
"""
from github import Github, GithubException
import config


class GithubReporter:
    def __init__(self):
        if not config.GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN не задан в .env")
        self._client = Github(config.GITHUB_TOKEN)
        self._repo = self._client.get_repo(config.GITHUB_REPO)

    def create_stale_issue(self, binding: dict) -> str:
        """Создаёт Issue по устаревшему разделу документации.
        binding — элемент stale_bindings[i]['binding'] из detector.py.
        Возвращает URL созданной задачи.
        """
        title = f"[Doc-sync] Устарел раздел: {binding['section_title']}"
        body = (
            f"**Документ:** `{binding['doc_file']}`\n"
            f"**Раздел (id):** `{binding['section_id']}`\n"
            f"**Утерянная связь (code_ref):** `{binding['code_ref']}`\n"
            f"**XPath:** `{binding['xpath']}`\n\n"
            f"Метод, на который ссылается раздел, изменён или удалён из "
            f"кода. Требуется актуализировать документацию.\n\n"
            f"_Создано автоматически git-doc-sync-agent._"
        )
        try:
            issue = self._repo.create_issue(title=title, body=body)
        except GithubException as e:
            raise RuntimeError(f"Не удалось создать Issue: {e}") from e
        return issue.html_url
