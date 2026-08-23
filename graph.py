import os
import sys
import json
import asyncio
from typing import Dict, Any, List, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

import config_sync as config
from detector import DocSyncDetector
from agents import ASTDetectiveAgent, XMLNavigatorAgent, DraftingAssistantAgent, DevOpsCoordinatorAgent
from git_pr_manager import GitPRManager


# --- СОСТОЯНИЕ ГРАФА (реальный LangGraph StateGraph) ---
class AgentState(TypedDict, total=False):
    """Состояние мультиагентного графа синхронизации кода и документации."""
    commit_hash: str
    changed_methods: List[Dict[str, Any]]
    stale_bindings: List[Dict[str, Any]]
    new_code_methods: List[Dict[str, Any]]
    needs_llm_review: bool
    ai_drafts: Dict[str, Any]
    approved_by_human: bool
    github_issue_body: str
    created_prs: List[Dict[str, Any]]
    current_step: str


def initial_state(**overrides: Any) -> AgentState:
    state: AgentState = {
        "commit_hash": "a1b2c3",
        "changed_methods": [],
        "stale_bindings": [],
        "new_code_methods": [],
        "needs_llm_review": False,
        "ai_drafts": {},
        "approved_by_human": False,
        "github_issue_body": "",
        "created_prs": [],
        "current_step": "start",
    }
    state.update(overrides)
    return state


# --- НОДЫ ГРАФА (ИИ-АГЕНТЫ) ---

async def node_ast_detect(state: AgentState) -> Dict[str, Any]:
    """Нода 1 (AST-Detective): детерминированная обёртка над detector.py/extractors.py.

    Без LLM: сканирует кодовую базу (AST — для Python через detector.py,
    tree-sitter — для остальных языков через extractors.py) и кладёт полный
    список найденных методов ("diff") в state графа. Никакой генерации
    текста и обращений к LLM на этом шаге."""
    print("[Node 1]: AST-Detective сканирует кодовую базу...")
    detector = DocSyncDetector()
    code_methods = detector.scan_codebase()

    changed = [
        {
            "signature": sig,
            "file": data["file"],
            "name": data["name"],
            "lineno": data["lineno"],
            "docstring": data["docstring"],
        }
        for sig, data in code_methods.items()
    ]

    return {"changed_methods": changed, "current_step": "ast_detect"}


async def node_xml_navigate(state: AgentState) -> Dict[str, Any]:
    """Нода 2 (XML-Navigator): детерминированное сопоставление по code_ref
    (та же логика, что в DocSyncDetector.scan_all_docs()).

    Без LLM: 1) изменённые методы, уже привязанные к <section code_ref=...>,
    помечаются как stale_bindings (нужно обновить XML). 2) Изменённые методы
    без привязки сопоставляются с заголовками разделов через косинусное
    сходство эмбеддингов (detector.calculate_semantic_similarity); если лучший
    результат <70%, выставляется needs_llm_review=True — сигнал для
    Drafting-Assistant, что нужен LLM, а не автопривязка."""
    print("[Node 2]: XML-Navigator сопоставляет код с документацией...")
    detector = DocSyncDetector()
    bindings = detector.scan_all_docs()
    documented_refs = {b["code_ref"] for b in bindings}
    changed_by_ref = {m["signature"]: m for m in state["changed_methods"]}

    stale_bindings = []
    for binding in bindings:
        if binding["code_ref"] in changed_by_ref:
            stale_bindings.append({
                "binding": binding,
                "reason": "Метод изменен. Требуется обновление XML-раздела.",
            })

    new_code_methods = []
    needs_llm_review = False
    for ref, method in changed_by_ref.items():
        if ref in documented_refs:
            continue  # уже обработан выше как stale_binding

        best_binding = None
        best_score = 0.0
        for binding in bindings:
            score = await detector.calculate_semantic_similarity(
                f"{method['name']} {method['docstring']}",
                binding["section_title"],
            )
            if score > best_score:
                best_score = score
                best_binding = binding

        item_needs_review = best_score < 0.7
        needs_llm_review = needs_llm_review or item_needs_review

        new_code_methods.append({
            "code_ref": ref,
            "file": method["file"],
            "method_name": method["name"],
            "suggested_binding": best_binding,
            "match_score": best_score,
            "needs_llm_review": item_needs_review,
        })

    return {
        "stale_bindings": stale_bindings,
        "new_code_methods": new_code_methods,
        "needs_llm_review": needs_llm_review,
        "current_step": "xml_navigate",
    }


async def node_ai_draft_writer(state: AgentState) -> Dict[str, Any]:
    """Нода 3 (Drafting-Assistant, Issue #9): реальный вызов Ollama/Qwen2.5
    (generate_draft — /api/generate, structured output {draft_text,
    confidence}, retry + fallback на TODO при ошибке/недоступности LLM)."""
    print("[Node 3]: Drafting-Assistant пишет ИИ-черновики правок...")
    drafts = {}
    writer = DraftingAssistantAgent()
    navigator = XMLNavigatorAgent()

    for item in state["stale_bindings"]:
        binding = item["binding"]
        method_name = binding["code_ref"]
        diff = f"Метод '{method_name}' изменён или удалён из кода."

        current_xml = ""
        doc_path = os.path.join(config.DOCS_DIR, binding["doc_file"])
        if os.path.exists(doc_path):
            with open(doc_path, "r", encoding="utf-8") as f:
                current_xml = navigator.extract_section_xml(f.read(), binding["section_id"])

        result = await writer.generate_draft(method_name, current_xml, diff)

        drafts[binding["section_id"]] = {
            "section_title": binding["section_title"],
            "doc_file": binding["doc_file"],
            "draft_text": result["draft_text"],
            "confidence": result["confidence"],
            "fallback": result["fallback"],
        }

    return {"ai_drafts": drafts, "current_step": "ai_draft_writer"}


async def node_human_review(state: AgentState) -> Dict[str, Any]:
    """Нода Human-in-the-Loop: сама ничего не делает — граф останавливается
    ПЕРЕД этой нодой через compile(interrupt_before=["human_review"]).
    После возобновления (graph.invoke(None, config)) approved_by_human уже
    выставлен снаружи (Streamlit/API), и conditional edge ниже решает маршрут."""
    print("[Human Review]: ожидание решения техписателя...")
    return {"current_step": "human_review"}


def route_after_human_review(state: AgentState) -> str:
    """Conditional edge: одобрено человеком -> DevOps-Coordinator, иначе -> END."""
    return "devops_coordinator" if state.get("approved_by_human") else END


async def node_devops_coordinator(state: AgentState) -> Dict[str, Any]:
    """Нода 4 (DevOps-Coordinator, Issue #10): для каждого устаревшего
    раздела реально вызывает GitPRManager.create_todo_pr() (PyGithub) —
    создаёт ветку docs-sync/patch-<section_id>, коммитит в неё draft_text
    от Drafting-Assistant вместо статичного TODO-шаблона и открывает
    настоящий Pull Request. Никакой симуляции ветки/PR тут больше нет.
    Отдельно, через LLM, готовится только текст GitHub Issue."""
    print("[Node 4]: DevOps-Coordinator создаёт реальные ветки/коммиты/PR...")
    coordinator = DevOpsCoordinatorAgent()
    issue_body = await coordinator.generate_issue_body(state["stale_bindings"])

    try:
        pr_manager = GitPRManager()
    except ValueError as e:
        # GITHUB_TOKEN не задан — реальные PR создать нельзя
        return {
            "github_issue_body": issue_body,
            "created_prs": [{"error": str(e)}],
            "current_step": "END",
        }

    created_prs: List[Dict[str, Any]] = []
    for item in state["stale_bindings"]:
        binding = item["binding"]
        section_id = binding["section_id"]
        draft = state["ai_drafts"].get(section_id)
        draft_text = draft["draft_text"] if draft else None

        try:
            # PyGithub — блокирующий клиент, выносим вызов в отдельный поток
            pr_url = await asyncio.to_thread(pr_manager.create_todo_pr, binding, draft_text)
            created_prs.append({
                "section_id": section_id,
                "doc_file": binding["doc_file"],
                "section_title": binding["section_title"],
                "pr_url": pr_url,
                "fallback": draft.get("fallback", True) if draft else True,
            })
        except Exception as e:
            created_prs.append({
                "section_id": section_id,
                "doc_file": binding["doc_file"],
                "section_title": binding["section_title"],
                "error": str(e),
            })

    return {
        "github_issue_body": issue_body,
        "created_prs": created_prs,
        "current_step": "END",
    }


# --- СБОРКА РЕАЛЬНОГО LANGGRAPH StateGraph ---

def build_workflow(checkpointer=None):
    """Собирает граф: ast_detect -> xml_navigate -> ai_draft_writer -> human_review
    -> (conditional) devops_coordinator | END. Граф прерывается перед human_review
    (interrupt_before) и требует внешнего resume после одобрения человеком."""
    workflow = StateGraph(AgentState)

    workflow.add_node("ast_detect", node_ast_detect)
    workflow.add_node("xml_navigate", node_xml_navigate)
    workflow.add_node("ai_draft_writer", node_ai_draft_writer)
    workflow.add_node("human_review", node_human_review)
    workflow.add_node("devops_coordinator", node_devops_coordinator)

    workflow.set_entry_point("ast_detect")
    workflow.add_edge("ast_detect", "xml_navigate")
    workflow.add_edge("xml_navigate", "ai_draft_writer")
    workflow.add_edge("ai_draft_writer", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {"devops_coordinator": "devops_coordinator", END: END},
    )
    workflow.add_edge("devops_coordinator", END)

    return workflow.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_before=["human_review"],
    )
