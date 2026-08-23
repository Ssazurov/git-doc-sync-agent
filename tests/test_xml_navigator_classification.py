"""
Eval-набор для XML-Navigator node (Issue #12): 5 сценариев diff'ов кода без
обращения к реальной LLM — DocSyncDetector.scan_all_docs и
calculate_semantic_similarity замоканы, чтобы классификация need_update /
new_section / review / skip была детерминированной.

Классификация new_code_methods (graph.NEW_SECTION_THRESHOLD=0.7,
graph.SKIP_THRESHOLD=0.35):
  >= 0.7            -> "new_section" (уверенная автопривязка)
  [0.35, 0.7)       -> "review"      (needs_llm_review=True)
  < 0.35            -> "skip"        (вероятно helper-метод)

Известное ограничение (зафиксировано тестами 2 и 3): node_xml_navigate
сверяет XML-привязки с ТЕКУЩИМ снимком кода (state["changed_methods"] из
node_ast_detect = все методы в репо), а не с diff'ом коммита. Поэтому удаление
и переименование метода не переводят старую XML-привязку в stale_bindings —
её code_ref просто перестаёт встречаться в снимке кода.
"""
import asyncio
from unittest.mock import patch, AsyncMock

from detector import DocSyncDetector
from graph import node_xml_navigate, initial_state


def _binding(code_ref, section_id, title):
    return {
        "doc_file": "d.xml",
        "section_id": section_id,
        "section_title": title,
        "code_ref": code_ref,
        "xpath": f"/section[@id='{section_id}']",
    }


def _method(signature, name, file, docstring=""):
    return {"signature": signature, "file": file, "name": name, "lineno": 1, "docstring": docstring}


def _run(bindings, changed_methods, similarity_score=0.0):
    state = initial_state(changed_methods=changed_methods)
    with patch.object(DocSyncDetector, "scan_all_docs", return_value=bindings), \
         patch.object(DocSyncDetector, "calculate_semantic_similarity",
                       new=AsyncMock(return_value=similarity_score)):
        return asyncio.run(node_xml_navigate(state))


def test_behavior_change_flags_need_update():
    """Тело метода изменилось, сигнатура/имя те же -> stale_bindings (need_update)."""
    ref = "payments.py::charge_customer"
    result = _run(
        bindings=[_binding(ref, "s1", "Оплата")],
        changed_methods=[_method(ref, "charge_customer", "payments.py", "изменённая логика")],
    )
    assert len(result["stale_bindings"]) == 1
    assert result["stale_bindings"][0]["binding"]["code_ref"] == ref
    assert result["new_code_methods"] == []


def test_deleted_method_not_flagged_stale_known_gap():
    """Метод удалён из кода -> его нет в changed_methods -> привязка НЕ попадает
    в stale_bindings (известное ограничение: сверка по снимку, не по diff'у)."""
    ref = "payments.py::charge_customer"
    result = _run(
        bindings=[_binding(ref, "s1", "Оплата")],
        changed_methods=[],
    )
    assert result["stale_bindings"] == []
    assert result["new_code_methods"] == []


def test_renamed_method_old_ref_not_stale_new_ref_classified():
    """Метод переименован: старый code_ref исчезает из снимка (та же особенность,
    что и delete), новое имя не задокументировано и классифицируется как обычный
    новый метод по best_score."""
    old_ref = "payments.py::charge_customer"
    new_ref = "payments.py::bill_customer"
    result = _run(
        bindings=[_binding(old_ref, "s1", "Оплата")],
        changed_methods=[_method(new_ref, "bill_customer", "payments.py")],
        similarity_score=0.8,
    )
    assert result["stale_bindings"] == []
    assert len(result["new_code_methods"]) == 1
    item = result["new_code_methods"][0]
    assert item["code_ref"] == new_ref
    assert item["classification"] == "new_section"
    assert item["needs_llm_review"] is False


def test_new_unrelated_method_needs_review():
    """Новый метод без чёткого соответствия ни одному разделу (0.35<=score<0.7)
    -> classification="review", needs_llm_review=True (сигнал для Drafting-Assistant)."""
    result = _run(
        bindings=[_binding("payments.py::charge_customer", "s1", "Оплата")],
        changed_methods=[_method("reports.py::generate_report", "generate_report", "reports.py")],
        similarity_score=0.5,
    )
    item = result["new_code_methods"][0]
    assert item["classification"] == "review"
    assert item["needs_llm_review"] is True
    assert result["needs_llm_review"] is True


def test_helper_method_not_documented_is_skipped():
    """Helper-метод (низкое сходство со всеми разделами, < 0.35) -> classification="skip",
    не требует ни ручного обновления, ни LLM-ревью."""
    result = _run(
        bindings=[_binding("payments.py::charge_customer", "s1", "Оплата")],
        changed_methods=[_method("utils.py::_format_date", "_format_date", "utils.py")],
        similarity_score=0.1,
    )
    item = result["new_code_methods"][0]
    assert item["classification"] == "skip"
    assert item["needs_llm_review"] is False
    assert result["needs_llm_review"] is False
