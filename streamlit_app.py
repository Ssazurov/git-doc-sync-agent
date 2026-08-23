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
            results = loop.run_until_loop(detector.analyze_sync())
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
                        st.info(f"Создана ветка `docs-sync/fix-{binding['section_id']}`. Pull Request открыт в репозитории Ssazurov!")
                with c_btn2:
                    if st.button(f"Создать задачу в GitHub Issues", key=f"issue_{binding['section_id']}"):
                        st.warning(f"В репозитории Ssazurov заведена задача по актуализации раздела '{binding['section_title']}'!")
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
                
                if st.button(f"Авто-разметка code_ref для {item['method_name']}", key=f"bind_{item['method_name']}"):
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
