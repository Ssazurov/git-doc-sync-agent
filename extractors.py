"""Мультиязычный слой извлечения функций/методов через tree-sitter.

Python обрабатывается отдельно через stdlib `ast` (см. detector.py) —
точнее для основного языка проекта и без доп. зависимости.
Здесь — C, C++, JavaScript, TypeScript, Go, Java, Rust.
"""
import os
from tree_sitter_language_pack import get_parser

# Node types, которые считаем "функцией/методом", по грамматикам tree-sitter
FUNC_NODE_TYPES = {
    "c": {"function_definition"},
    "cpp": {"function_definition"},
    "javascript": {"function_declaration", "method_definition"},
    "typescript": {"function_declaration", "method_definition"},
    "tsx": {"function_declaration", "method_definition"},
    "go": {"function_declaration", "method_declaration"},
    "java": {"method_declaration", "constructor_declaration"},
    "rust": {"function_item"},
}

# Сопоставление расширений файлов с грамматикой tree-sitter
EXT_TO_LANG = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}

COMMENT_NODE_TYPES = {"comment", "line_comment", "block_comment"}

SUPPORTED_EXTENSIONS = {".py"} | set(EXT_TO_LANG.keys())

_parsers_cache: dict = {}


def _get_parser(lang: str):
    if lang not in _parsers_cache:
        _parsers_cache[lang] = get_parser(lang)
    return _parsers_cache[lang]


_NAME_NODE_TYPES = ("identifier", "field_identifier", "type_identifier")


def _find_identifier(node) -> str | None:
    """DFS: первый identifier-подобный узел в поддереве (имя функции стоит раньше параметров)."""
    if node.type in _NAME_NODE_TYPES:
        return node.text.decode()
    for child in node.children:
        found = _find_identifier(child)
        if found:
            return found
    return None


def _find_name(node) -> str | None:
    """Достаёт имя функции/метода из декларации узла.

    JS/TS/Go/Java/Rust отдают имя прямо в поле "name". C/C++ прячут его
    внутри "declarator" (function_declarator, возможно обёрнутый
    pointer_declarator) — там ищем первый identifier.
    """
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode()
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        found = _find_identifier(declarator)
        if found:
            return found
    return _find_identifier(node)


def _leading_comment(node, src: bytes) -> str:
    """Блок комментариев прямо перед узлом — аналог docstring для не-Python."""
    lines = []
    prev = node.prev_sibling
    while prev is not None and prev.type in COMMENT_NODE_TYPES:
        lines.insert(0, src[prev.start_byte:prev.end_byte].decode(errors="ignore"))
        prev = prev.prev_sibling
    return "\n".join(lines)


def extract_methods(filepath: str) -> list[dict]:
    """Извлекает функции/методы из C/C++/JS/TS/Go/Java/Rust файла через tree-sitter."""
    ext = os.path.splitext(filepath)[1]
    lang = EXT_TO_LANG.get(ext)
    if lang is None:
        return []

    methods = []
    try:
        with open(filepath, "rb") as f:
            src = f.read()
        parser = _get_parser(lang)
        tree = parser.parse(src)
        target_types = FUNC_NODE_TYPES[lang]

        def walk(node):
            if node.type in target_types:
                name = _find_name(node)
                if name:
                    methods.append({
                        "name": name,
                        "lineno": node.start_point[0] + 1,
                        "docstring": _leading_comment(node, src),
                        "signature": f"{os.path.basename(filepath)}::{name}",
                    })
            for child in node.children:
                walk(child)

        walk(tree.root_node)
    except Exception as e:
        print(f"[ERROR] tree-sitter парсинг {filepath} ({lang}): {e}")
    return methods
