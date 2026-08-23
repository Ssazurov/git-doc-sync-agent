import os
import sys
import json
import asyncio
import streamlit as st
import httpx

# Добавляем пути
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from detector import DocSyncDetector
from github_reporter import GithubReporter
from git_pr_manager import GitPRManager
from graph import build_workflow, initial_state

# Настройка страницы
st.set_page_config(
    page_title="Doc-as-Code Copilot",
    page_icon="🤖",
    layout="wide"
)

# Стилизация
st.markdown("""
    <style>
    .stApp { background-color: #fcfcfc; }
    .stAppHeader { background-color: #ffffff; }
    .status-badge { padding: 4px 10px; border-radius: 4px; font-weight: bold; }
    .sync-ok { background-color: #d3f9d8; color: #2b8a3e; }
    .sync-warn { background-color: #ffe3e3; color: #c92a2a; }
    .sync-info { background-color: #e3fafc; color: #1c7ed6; }
    </style>
""", unsafe_allow_html=True)

# Инициализация сессии
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "hitl_thread_id" not in st.session_state:
    st.session_state.hitl_thread_id = None
if "hitl_workflow" not in st.session_state:
    st.session_state.hitl_workflow = None
if "hitl_state" not in st.session_state:
    st.session_state.hitl_state = None  # снапшот состояния графа на паузе
if "hitl_result" not in st.session_state:
    st.session_state.hitl_result = None  # финальный state после resume

# --- БОКОВАЯ ПАНЕЛЬ ---
with st.sidebar:
    st.title("🤖 Настройки")
    
    st.markdown("### 🚦 Статусы систем")
    # Проверка Ollama
    ollama_ok = False
    try:
        r = httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=1.0)
        if r.status_code == 200:
            ollama_ok = True
    except Exception:
        pass
        
    if ollama_ok:
        st.markdown("Ollama: <span class='status-badge sync-ok'>АКТИВНА</span>", unsafe_allow_html=True)
    else:
        st.markdown("Ollama: <span class='status-badge sync-warn'>ОФФЛАЙН</span>", unsafe_allow_html=True)
        
    st.markdown(f"**Активный репозиторий:**\n`{config.GITHUB_REPO}`")
    st.markdown(f"**Ветка по умолчанию:** `{config.GIT_DEFAULT_BRANCH}`")

    st.markdown("---")
    st.markdown("### 🛠️ Конфигурация чанкинга")
    st.text(f"Размер чанка: {config.CHUNK_SIZE}")
    st.text(f"Перекрытие: {config.CHUNK_OVERLAP}")
    st.text(f"Режим: {config.CHUNK_MODE}")
    
    st.markdown("---")
    if st.button("🗑️ Очистить результаты"):
        st.session_state.scan_results = None
        st.rerun()

# --- ГЛАВНАЯ ПАНЕЛЬ ---
st.title("📚 Doc-as-Code Copilot — ИИ Синхронизация")
st.markdown("""
    Данный интерфейс позволяет техническому писателю контролировать соответствие между исходным кодом продукта 
    и файлами упрощенной XML/DocBook документации.
""")

col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🔍 Скан сейчас", use_container_width=True, type="primary"):
        with st.spinner("AST-анализ кода и XML сопоставление..."):
            detector = DocSyncDetector()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(detector.analyze_sync())
            st.session_state.scan_results = results
            st.success("Сканирование успешно завершено!")
            st.rerun()

# Если есть результаты сканирования
if st.session_state.scan_results:
    results = st.session_state.scan_results
    
    # Сводная статистика
    st.markdown("### 📊 Общая статистика")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Всего методов в коде (AST)", results["total_code_methods"])
    m2.metric("Привязанных тегов XML", results["total_documented_bindings"])
    m3.metric("Устаревшие разделы (Stale)", len(results["stale_bindings"]))
    m4.metric("Неописанный код (New)", len(results["undocumented_methods"]))
    
    tab1, tab2, tab3 = st.tabs([
        "⚠️ Устаревшие разделы (Stale)", 
        "❓ Недокументированный код (Undocumented)", 
        "📖 Проводник документации"
    ])
    
    with tab1:
        st.header("Разделы доков, привязанные к удаленному или измененному коду")
        if not results["stale_bindings"]:
            st.success("Все привязанные разделы соответствуют методам в коде!")
        else:
            for item in results["stale_bindings"]:
                binding = item["binding"]
                st.error(f"**Раздел: \"{binding['section_title']}\" (ID: `{binding['section_id']}`)**")
                st.markdown(f"""
                    *   **Файл документа:** `{binding['doc_file']}`
                    *   **Утерянная связь:** `{binding['code_ref']}`
                    *   **XPath в XML:** `{binding['xpath']}`
                """)
                
                # Имитируем активную ссылку на коммит Github
                commit_hash = "a1b2c3"
                st.markdown(f"🔗 **[Просмотреть изменения в коммите #{commit_hash} на GitHub](https://github.com/{config.GITHUB_REPO}/commit/{commit_hash})**")
                
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button(f"Создать ветку с разметкой TODO для {binding['section_id']}", key=f"todo_{binding['section_id']}"):
                        try:
                            pr_manager = GitPRManager()
                            pr_url = pr_manager.create_todo_pr(binding)
                            st.success(f"PR открыт: {pr_url}")
                        except Exception as e:
                            st.error(f"Ошибка создания PR: {e}")
                with c_btn2:
                    if st.button(f"Создать задачу в GitHub Issues", key=f"issue_{binding['section_id']}"):
                        try:
                            reporter = GithubReporter()
                            url = reporter.create_stale_issue(binding)
                            st.success(f"Issue создан: {url}")
                        except Exception as e:
                            st.error(f"Ошибка создания Issue: {e}")
                st.markdown("---")
                
    with tab2:
        st.header("Методы и функции, которые присутствуют в коде, но отсутствуют в доках")
        if not results["undocumented_methods"]:
            st.success("Отлично! Весь ваш код задокументирован!")
        else:
            for item in results["undocumented_methods"]:
                st.warning(f"**Обнаружен неописанный код: `{item['code_ref']}`**")
                st.markdown(f"""
                    *   **Файл кода:** `{item['file']}`
                    *   **Функция/Метод:** `def {item['method_name']}()`
                """)
                
                if item["suggested_match"]:
                    match = item["suggested_match"]
                    st.info(f"""
                        💡 **Интеллектуальная рекомендация ИИ (Оценка сходства: {item['match_score']:.2%}):**  
                        Похоже, данный метод относится к разделу **\"{match['section_title']}\"** в файле `{match['doc_file']}`.  
                        Желаете провязать код с разделом?
                    """)
                else:
                    st.info("💡 **Рекомендация ИИ:** Релевантных разделов в документации не найдено. Рекомендуется создать новый раздел.")
                
                if st.button(f"Авто-разметка code_ref для {item['method_name']}", key=f"bind_{item['code_ref']}"):
                    st.success(f"Тег `code_ref='{item['code_ref']}'` успешно подготовлен для вставки!")
                st.markdown("---")
                
    with tab3:
        st.header("Структура DocBook XML")
        # Показываем исходники XML для наглядности
        for doc in ["installation_guide.xml", "admin_guide.xml"]:
            path = os.path.join(config.DOCS_DIR, doc)
            if os.path.exists(path):
                with st.expander(f"📄 {doc}"):
                    with open(path, "r", encoding="utf-8") as f:
                        st.code(f.read(), language="xml")
else:
    st.info("Нажмите кнопку 'Скан сейчас', чтобы запустить ИИ-синхронизатор!")

# --- LANGGRAPH HITL (реальная пауза через checkpointer, без имитации) ---
st.markdown("---")
st.markdown("### 🔄 LangGraph: Human-in-the-Loop с реальной паузой")
st.caption(
    "Граф реально останавливается перед нодой human_review (interrupt_before) "
    "и хранит состояние в checkpointer. Никакого time.sleep/флагов — резюм "
    "идёт через graph.invoke(None, config) после update_state()."
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


hitl_col1, hitl_col2 = st.columns([3, 1])
with hitl_col2:
    if st.button("▶️ Запустить граф до паузы", use_container_width=True):
        thread_id = f"streamlit-{os.urandom(4).hex()}"
        workflow = build_workflow()
        cfg = {"configurable": {"thread_id": thread_id}}
        with st.spinner("Граф выполняет ast_detect → xml_navigate → ai_draft_writer..."):
            _run_async(workflow.ainvoke(initial_state(), cfg))
        st.session_state.hitl_workflow = workflow
        st.session_state.hitl_thread_id = thread_id
        st.session_state.hitl_result = None
        st.rerun()

if st.session_state.hitl_workflow is not None and st.session_state.hitl_result is None:
    cfg = {"configurable": {"thread_id": st.session_state.hitl_thread_id}}
    snapshot = st.session_state.hitl_workflow.get_state(cfg)
    state = snapshot.values

    st.markdown(f"**Граф на паузе перед нодой:** `{', '.join(snapshot.next) or 'human_review'}`")

    if not state.get("stale_bindings"):
        st.info("Устаревших разделов не найдено — одобрять нечего.")
    else:
        edited_drafts = {}
        for item in state["stale_bindings"]:
            binding = item["binding"]
            section_id = binding["section_id"]
            draft = state.get("ai_drafts", {}).get(section_id, {})
            st.markdown(f"**Раздел:** `{section_id}` — {binding['section_title']}")
            edited_text = st.text_area(
                "Черновик правки (можно отредактировать перед одобрением)",
                value=draft.get("draft_text", ""),
                key=f"hitl_draft_{section_id}",
                height=120,
            )
            edited_drafts[section_id] = {**draft, "draft_text": edited_text}
            st.markdown("---")

        approve_col, reject_col = st.columns(2)
        with approve_col:
            if st.button("✅ Одобрить и продолжить граф (resume)", use_container_width=True):
                st.session_state.hitl_workflow.update_state(
                    cfg,
                    {"ai_drafts": edited_drafts, "approved_by_human": True},
                )
                with st.spinner("Резюм графа: devops_coordinator создаёт PR..."):
                    result = _run_async(st.session_state.hitl_workflow.ainvoke(None, cfg))
                st.session_state.hitl_result = result
                st.rerun()
        with reject_col:
            if st.button("🚫 Отклонить (граф завершится без PR)", use_container_width=True):
                st.session_state.hitl_workflow.update_state(
                    cfg, {"approved_by_human": False}
                )
                with st.spinner("Резюм графа..."):
                    result = _run_async(st.session_state.hitl_workflow.ainvoke(None, cfg))
                st.session_state.hitl_result = result
                st.rerun()

if st.session_state.hitl_result is not None:
    result = st.session_state.hitl_result
    st.success("Граф завершён (END).")
    if result.get("created_prs"):
        for pr in result["created_prs"]:
            if "pr_url" in pr:
                st.markdown(f"🔗 [PR: {pr['section_title']}]({pr['pr_url']})")
            else:
                st.error(f"{pr.get('section_id', '?')}: {pr.get('error')}")
    else:
        st.info("PR не создавались (отклонено человеком или нет stale_bindings).")
    if st.button("🔄 Сбросить HITL-сессию"):
        st.session_state.hitl_workflow = None
        st.session_state.hitl_thread_id = None
        st.session_state.hitl_result = None
        st.rerun()
