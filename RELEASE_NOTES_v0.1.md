# v0.1 — первый релиз

Doc-as-Code copilot: находит рассинхронизацию между кодом (Python AST) и документацией (DocBook XML / Markdown с code_ref).

## Возможности
- detector.py — сканирует код через ast и документацию через lxml, находит устаревшие (stale) разделы и недокументированные методы, семантический матчинг через Ollama embeddings (fallback — пересечение слов).
- streamlit_app.py — портал техписателя со статусами разделов и действиями.
- github_reporter.py — автосоздание GitHub Issue по устаревшему разделу.
- git_pr_manager.py — автосоздание ветки/PR с TODO-разметкой в XML.
- CI: .github/workflows/doc_sync_check.yml — проверка синхронизации на push/PR в main.

## Изменения в этом релизе
- Документация перенесена в docs/ (installation_guide.xml, admin_guide.xml, writer_manual.md, architecture.md).
- Добавлены github_reporter.py и git_pr_manager.py (PyGithub-интеграция).
- Исправлен баг импорта в config.py.
- db/ (генерируемое состояние синхронизации) добавлен в .gitignore.

## Установка
pip install -r requirements.txt
cp .env.example .env
python detector.py
streamlit run streamlit_app.py
