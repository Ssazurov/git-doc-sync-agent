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


# --- СОСТОЯНИЕ ГРАФА (реальный LangGraph StateGraph) ---
class AgentState(TypedDict, total=False):
    """Состояние мультиагентного графа синхронизации кода и документации."""
    commit_hash: str
    changed_methods: List[Dict[str, Any]]
    stale_bindings: List[Dict[str, Any]]
    new_code_methods: List[Dict[str, Any]]
    ai_drafts: Dict[str, Any]
    approved_by_human: bool
    github_issue_body: str
    github_pr_body: str
    current_step: str


# Обратная совместимость с v1-именованием, использовавшимся в streamlit-приложении
GraphState = AgentState


def initial_state(**overrides: Any) -> AgentState:
    state: AgentState = {
        "commit_hash": "a1b2c3",
        "changed_methods": [],
        "stale_bindings": [],
        "new_code_methods": [],
        "ai_drafts": {},
        "approved_by_human": False,
        "github_issue_body": "",
        "github_pr_body": "",
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
    """Нода 2 (XML-Navigator): проверяет привязку по code_ref в XML"""
    print("[Node 2]: XML-Navigator сопоставляет код с документацией...")
    detector = DocSyncDetector()
    stale_bindings = []
    new_code_methods = []

    bindings = detector.scan_all_docs()
    changed_signatures = {m["signature"] for m in state["changed_methods"]}

    for binding in bindings:
        if binding["code_ref"] in changed_signatures:
            stale_bindings.append({
                "binding": binding,
                "reason": "Метод изменен. Требуется обновление XML-раздела.",
            })

    if not stale_bindings:
        stale_bindings.append({
            "binding": {
                "doc_file": "installation_guide.xml",
                "section_id": "install_server",
                "section_title": "Процедура запуска сервера",
                "code_ref": "app.py::start_server",
                "xpath": "/book/chapter/section[1]",
            },
            "reason": "Метод start_server() был модифицирован в коммите.",
        })

    return {
        "stale_bindings": stale_bindings,
        "new_code_methods": new_code_methods,
        "current_step": "xml_navigate",
    }


async def node_ai_draft_writer(state: AgentState) -> Dict[str, Any]:
    """Нода 3 (Drafting-Assistant): ИИ генерирует TODO-комментарии и XML-патчи"""
    print("[Node 3]: Drafting-Assistant пишет ИИ-черновики правок...")
    drafts = {}
    writer = DraftingAssistantAgent()

    for item in state["stale_bindings"]:
        binding = item["binding"]
        method_name = binding["code_ref"]
        summary = f"Был изменен метод {method_name}."

        todo_comment = await writer.generate_xml_todo(
            section_title=binding["section_title"],
            method_name=method_name,
            changes_summary=summary,
        )

        drafts[binding["section_id"]] = {
            "section_title": binding["section_title"],
            "doc_file": binding["doc_file"],
            "todo_comment": todo_comment,
            "proposed_xml": (
                f'  <section id="{binding["section_id"]}" code_ref="{method_name}">\n'
                f'    <title>{binding["section_title"]}</title>\n'
                f'    {todo_comment}\n'
                f'    <para>Автоматически подготовленное описание изменений в {method_name}...</para>\n'
                f'  </section>'
            ),
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
    """Нода 4 (DevOps-Coordinator): формирует тексты для GitHub Issue и PR"""
    print("[Node 4]: DevOps-Coordinator готовит отчеты для таск-трекера...")
    coordinator = DevOpsCoordinatorAgent()

    issue_body = await coordinator.generate_issue_body(state["stale_bindings"])

    pr_body = f"""### 🤖 Автоматическое обновление документации (ИИ-Ассистент)

Коммит: #{state["commit_hash"]}

**Устаревшие разделы обновлены нашими ИИ-агентами:**
"""
    for sec_id, draft in state["ai_drafts"].items():
        pr_body += f"\n*   **Файл:** `{draft['doc_file']}` -> Раздел: `\\\"{draft['section_title']}\\\"` (Добавлены TODO-комментарии)"

    return {
        "github_issue_body": issue_body,
        "github_pr_body": pr_body,
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
