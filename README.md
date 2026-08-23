# git-doc-sync-agent 🤖📚

**Doc-as-Code copilot**, который следит, чтобы техническая документация не
расходилась с кодом. Разбирает код (Python, C, C++, JavaScript, TypeScript,
Go, Java, Rust) через AST/tree-sitter, сверяет со связями `code_ref` в
XML/DocBook-документации, находит устаревшие разделы и недокументированный
код, а по команде техписателя сам заводит GitHub Issue или открывает Pull
Request с TODO-разметкой.

Никакого «магического» LLM-агента, который тихо правит документацию за
человека: детерминированный анализ (AST + XPath) даёт список фактов,
Ollama-эмбеддинги — необязательная подсказка для маппинга, а решение и
финальный merge всегда остаются за техписателем.

## Проблема, которую решает проект

В большинстве команд документация — отдельная сущность: код меняется в PR,
а раздел мануала «Установка» продолжает ссылаться на давно удалённый
параметр. Инструмент делает связь между кодом и доками явной и проверяемой:
- Раздел XML помечается атрибутом `code_ref="file.py::method"`.
- Детектор на каждый прогон сверяет, существует ли ещё такой метод в коде.
- Расхождение — не догадка LLM, а факт: метод есть/метода нет.

## Как это работает

```mermaid
flowchart TD
    A[Запуск detector.py<br/>push / PR / вручную] --> B[Сканер кода<br/>ast: .py · tree-sitter: .c/.cpp/.js/.ts/.go/.java/.rs]
    B --> C[Индекс методов<br/>file.ext::method_name]
    A --> D[XML-сканер docs/*.xml<br/>lxml XPath //section@code_ref]
    D --> E[Список привязок code_ref]
    C --> F{analyze_sync}
    E --> F
    F -->|code_ref есть в XML,<br/>метода нет в коде| G[Stale bindings<br/>раздел устарел]
    F -->|метод в коде,<br/>нет code_ref| H[Undocumented methods]
    H --> I[Semantic match:<br/>Ollama embeddings,<br/>fallback — пересечение слов]
    I --> J[Похожий раздел XML + score]
    G --> K[(sync_state.json)]
    J --> K
    K --> L[Streamlit-портал]
    L --> M["Действия техписателя:<br/>создать Issue / открыть PR с TODO"]
```

1. `detector.py` парсит код (`ast` для Python, `tree-sitter` для C/C++/JS/TS/Go/Java/Rust — модуль `extractors.py`) и документацию через `lxml` независимо друг от друга.
2. Раздел с `code_ref="file.py::method"` считается **stale**, если такого метода уже нет в коде.
3. Метод без обратной ссылки из XML попадает в **undocumented** — для него ищется семантически похожий раздел (эмбеддинги Ollama, при недоступности — пересечение слов, порог 35%).
4. Результат пишется в `sync_state.json` и рендерится в Streamlit-портале.
5. Техписатель одной кнопкой заводит **GitHub Issue** (`github_reporter.py`) или **PR с TODO-комментарием** в самом XML (`git_pr_manager.py`) — целиком через GitHub API, без локального `git`.
6. CI (`doc_sync_check.yml`) гоняет `detector.py` на каждый push/PR в `main` и публикует отчёт.

## Self-monitoring

`docs/installation_guide.xml` и `docs/admin_guide.xml` — тестовая
документация самого проекта с `code_ref` на его же методы. Часть ссылок
намеренно устарела (например, `ingest.py::get_embedding_function` — файла
`ingest.py` в проекте нет), чтобы можно было сразу увидеть детектор в
действии без внешнего репозитория. Реальный пример находки —
[Issue #1](https://github.com/Ssazurov/git-doc-sync-agent/issues/1),
созданный самим `github_reporter.py`.

## Компоненты

| Файл | Роль |
|---|---|
| `detector.py` | Сканер кода (ast + tree-sitter) + XPath-сканер XML, вычисляет stale/undocumented, сохраняет `sync_state.json` |
| `extractors.py` | tree-sitter-извлечение функций/методов для C/C++/JS/TS/Go/Java/Rust |
| `streamlit_app.py` | Портал техписателя: статусы разделов, метрики, кнопки действий |
| `github_reporter.py` | Создаёт GitHub Issue по устаревшему разделу (PyGithub) |
| `git_pr_manager.py` | Создаёт ветку, вставляет TODO в XML, открывает PR — через GitHub Contents/Git API |
| `config.py` | Настройки из `.env` |
| `docs/` | Тестовая self-monitoring документация |
| `.github/workflows/doc_sync_check.yml` | CI-проверка на push/PR в `main` |

## Технологии

`Python 3.10+` · `ast` (stdlib, для Python) · `tree-sitter` +
`tree-sitter-language-pack` (для C/C++/JS/TS/Go/Java/Rust) ·
`lxml` (XPath) · `httpx` (async) · `Ollama` (embeddings, опционально) ·
`Streamlit` · `PyGithub` · `GitHub Actions`

## Поддерживаемые языки кода

| Язык | Расширения | Парсер |
|---|---|---|
| Python | `.py` | `ast` (stdlib) |
| C | `.c`, `.h` | tree-sitter |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh` | tree-sitter |
| JavaScript | `.js`, `.jsx` | tree-sitter |
| TypeScript | `.ts`, `.tsx` | tree-sitter |
| Go | `.go` | tree-sitter |
| Java | `.java` | tree-sitter |
| Rust | `.rs` | tree-sitter |

Для не-Python языков вместо docstring используется блок комментариев
непосредственно перед функцией/методом (`//`, `/** */`).

## Установка и запуск

```bash
git clone https://github.com/Ssazurov/git-doc-sync-agent.git
cd git-doc-sync-agent
pip install -r requirements.txt
cp .env.example .env          # заполнить переменные (см. таблицу ниже)
python detector.py            # разовый анализ + краткий отчёт в консоль
streamlit run streamlit_app.py   # интерактивный портал техписателя
```

Для создания Issue/PR из UI нужен `GITHUB_TOKEN` с правами на репозиторий
из `GITHUB_REPO`. Семантический матчинг работает без Ollama (fallback на
пересечение слов), но качественнее — с локально поднятой Ollama.

## Переменные окружения (`.env`)

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `GIT_REPO_PATH` | путь к репозиторию с кодом | `./` |
| `GIT_DEFAULT_BRANCH` | ветка по умолчанию | `main` |
| `GITHUB_TOKEN` | токен для PyGithub (создание Issue/PR) | — |
| `GITHUB_REPO` | `owner/repo` | `Ssazurov/git-doc-sync-agent` |
| `DOCS_DIR` | папка документации | `./docs` |
| `SYNC_STATE_FILE` | файл со статусами (генерируется) | `./db/sync_state.json` |
| `OLLAMA_HOST` | адрес локальной LLM для эмбеддингов | — |
| `OLLAMA_EMBED_MODEL` | модель эмбеддингов | `nomic-embed-text` |

Подробнее об архитектуре и что уже реализовано, а что в планах:
[`docs/architecture.md`](docs/architecture.md). Инструкция для техписателя
по работе с порталом: [`docs/writer_manual.md`](docs/writer_manual.md).

## Известные ограничения

- Детектор сравнивает *текущее* состояние кода и доков, а не diff между
  коммитами — это не история изменений, а снимок расхождений на момент запуска.
- Семантический матчинг — вспомогательная подсказка (эмбеддинги/пересечение
  слов), не гарантия точного соответствия; решение всегда за человеком.
- Мультиагентного оркестратора (LangGraph и т.п.) нет и не планируется —
  вся логика синхронный/асинхронный Python в `DocSyncDetector`.

## Лицензия

См. [`LICENSE.md`](LICENSE.md).


<img width="2560" height="1372" alt="image" src="https://github.com/user-attachments/assets/e1f60fc9-02e3-4e84-a2a6-3ef9950709f7" />

<img width="2560" height="1372" alt="image" src="https://github.com/user-attachments/assets/2f7ee914-4980-4f97-8ed1-9ba1c2e73577" />

<img width="2560" height="1372" alt="image" src="https://github.com/user-attachments/assets/5f52ca9d-cfd3-4617-8536-58456a72c88a" />

<img width="2560" height="1372" alt="image" src="https://github.com/user-attachments/assets/646a807a-7b24-4e69-bd4b-36aef8f36f9f" />
