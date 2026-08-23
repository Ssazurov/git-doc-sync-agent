"""
Git-PR-Manager: создаёт ветку docs-sync/patch-<section_id>, вставляет
TODO-комментарий перед устаревшим <section> в XML и открывает Pull
Request — всё через GitHub Contents/Git API (PyGithub), без локального
git-клиента.
"""
import base64
from github import Github, GithubException
import config

TODO_TEMPLATE = (
    "<!-- TODO(doc-sync): раздел устарел — code_ref '{code_ref}' "
    "изменён или удалён из кода. Актуализируйте текст ниже. -->\n"
)


class GitPRManager:
    def __init__(self):
        if not config.GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN не задан в .env")
        self._client = Github(config.GITHUB_TOKEN)
        self._repo = self._client.get_repo(config.GITHUB_REPO)

    def _candidate_paths(self, doc_file: str) -> list[str]:
        """Пробуем путь из DOCS_DIR, затем — корень репозитория
        (реальные .xml сейчас лежат в корне, а не в docs/)."""
        docs_dir = config.DOCS_DIR.lstrip("./").strip("/")
        paths = []
        if docs_dir:
            paths.append(f"{docs_dir}/{doc_file}")
        paths.append(doc_file)
        # без дублей, сохраняя порядок
        seen = set()
        return [p for p in paths if not (p in seen or seen.add(p))]

    def _get_file(self, doc_file: str, ref: str):
        last_err = None
        for path in self._candidate_paths(doc_file):
            try:
                return path, self._repo.get_contents(path, ref=ref)
            except GithubException as e:
                last_err = e
        raise RuntimeError(
            f"Файл '{doc_file}' не найден в репозитории ни по одному "
            f"из путей {self._candidate_paths(doc_file)}: {last_err}"
        )

    def create_todo_pr(self, binding: dict) -> str:
        """Создаёт ветку, вставляет TODO перед устаревшим <section>,
        коммитит и открывает PR. Возвращает URL PR."""
        base_branch = config.GIT_DEFAULT_BRANCH
        section_id = binding["section_id"]
        branch_name = f"docs-sync/patch-{section_id}"

        base_ref = self._repo.get_git_ref(f"heads/{base_branch}")
        base_sha = base_ref.object.sha

        # Ветка: если уже существует — переиспользуем
        try:
            self._repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
        except GithubException as e:
            if e.status != 422:  # 422 = ref already exists
                raise RuntimeError(f"Не удалось создать ветку: {e}") from e

        path, file_content = self._get_file(binding["doc_file"], ref=branch_name)
        raw = base64.b64decode(file_content.content).decode("utf-8")

        marker = f'<section id="{section_id}"'
        if marker not in raw:
            raise RuntimeError(
                f"Секция id='{section_id}' не найдена в {path} — "
                f"структура файла не совпадает с ожидаемой"
            )
        todo = TODO_TEMPLATE.format(code_ref=binding["code_ref"])
        new_raw = raw.replace(marker, todo + marker, 1)

        self._repo.update_file(
            path=path,
            message=f"docs: TODO по устаревшему разделу '{binding['section_title']}'",
            content=new_raw,
            sha=file_content.sha,
            branch=branch_name,
        )

        pr_title = f"[Doc-sync] TODO: {binding['section_title']}"
        pr_body = (
            f"Автоматически сгенерировано git-doc-sync-agent.\n\n"
            f"- **Документ:** `{path}`\n"
            f"- **Раздел:** `{section_id}`\n"
            f"- **Устаревший code_ref:** `{binding['code_ref']}`\n\n"
            f"В раздел вставлен TODO-комментарий. Доработайте текст и "
            f"смержите вручную."
        )
        try:
            pr = self._repo.create_pull(
                title=pr_title, body=pr_body, head=branch_name, base=base_branch
            )
        except GithubException as e:
            if e.status == 422:
                # PR из этой ветки уже существует — найдём и вернём его
                existing = self._repo.get_pulls(
                    state="open", head=f"{self._repo.owner.login}:{branch_name}"
                )
                for p in existing:
                    return p.html_url
            raise RuntimeError(f"Не удалось открыть PR: {e}") from e
        return pr.html_url
