import os
import ast
import re
import json
import httpx
from lxml import etree
import config

class DocSyncDetector:
    """
    Интеллектуальное ядро системы Doc-as-Code Copilot.
    Анализирует AST Python-кода, парсит simplified DocBook XML и находит:
    1. Измененные / удаленные методы, привязанные к XML (Stale sections).
    2. Новые или измененные методы без привязки к XML (Undocumented code).
    3. Вычисляет семантическое соответствие между недокументированным кодом и заголовками XML, предлагая авто-маппинг.
    """
    
    def __init__(self):
        self.codes_dir = config.GIT_REPO_PATH
        self.docs_dir = config.DOCS_DIR
        self.state_file = config.SYNC_STATE_FILE

    def extract_python_methods(self, filepath: str) -> list[dict]:
        """Парсит файл Python через AST и достает все функции/методы и их docstrings"""
        methods = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)
                
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    docstring = ast.get_docstring(node) or ""
                    methods.append({
                        "name": node.name,
                        "lineno": node.lineno,
                        "docstring": docstring,
                        "signature": f"{os.path.basename(filepath)}::{node.name}"
                    })
        except Exception as e:
            print(f"[ERROR] Ошибка AST-парсинга {filepath}: {e}")
        return methods

    def scan_codebase(self) -> dict[str, dict]:
        """Сканирует всю папку с кодом и индексирует методы"""
        all_methods = {}
        EXCLUDE_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", ".idea", ".pytest_cache", "db"}
        for root, dirs, files in os.walk(self.codes_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                if file.endswith(".py") and not file.startswith("test_") and file != "config.py":
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, self.codes_dir)
                    for method in self.extract_python_methods(path):
                        sig = f"{rel_path}::{method['name']}"
                        all_methods[sig] = {
                            "file": rel_path,
                            "name": method["name"],
                            "lineno": method["lineno"],
                            "docstring": method["docstring"]
                        }
        return all_methods

    def scan_docbook_xml(self, filepath: str) -> list[dict]:
        """Считывает упрощенный DocBook XML и извлекает привязанный code_ref"""
        bindings = []
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            tree = etree.parse(filepath, parser)
            root = tree.getroot()
            
            # Находим все теги <section>, имеющие атрибут code_ref
            sections = root.xpath("//section[@code_ref]")
            for sec in sections:
                bindings.append({
                    "doc_file": os.path.basename(filepath),
                    "section_id": sec.get("id"),
                    "section_title": sec.find("title").text if sec.find("title") is not None else "Без названия",
                    "code_ref": sec.get("code_ref"),
                    "xpath": tree.getpath(sec)
                })
        except Exception as e:
            print(f"[ERROR] Не удалось прочитать XML {filepath}: {e}")
        return bindings

    def scan_all_docs(self) -> list[dict]:
        """Сканирует все XML-файлы в паблике документации"""
        all_bindings = []
        if not os.path.exists(self.docs_dir):
            return []
        for file in os.listdir(self.docs_dir):
            if file.endswith(".xml"):
                all_bindings.extend(self.scan_docbook_xml(os.path.join(self.docs_dir, file)))
        return all_bindings

    _embed_cache: dict = {}

    async def _get_embedding(self, client: httpx.AsyncClient, url: str, text: str) -> list:
        if text in self._embed_cache:
            return self._embed_cache[text]
        r = await client.post(url, json={"model": config.OLLAMA_EMBED_MODEL, "prompt": text})
        v = r.json()["embedding"]
        self._embed_cache[text] = v
        return v

    async def calculate_semantic_similarity(self, text1: str, text2: str) -> float:
        """Запрашивает эмбеддинги через Ollama (с кэшем) и вычисляет косинусное сходство"""
        if config.EMBED_PROVIDER == "openai":
            # Заглушка для OpenAI API
            return 0.5
            
        url = f"{config.OLLAMA_HOST}/api/embeddings"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                v1 = await self._get_embedding(client, url, text1)
                v2 = await self._get_embedding(client, url, text2)
                
                # Косинусное сходство (dot product / magnitudes)
                dot_product = sum(a*b for a, b in zip(v1, v2))
                mag1 = sum(a*a for a in v1) ** 0.5
                mag2 = sum(b*b for b in v2) ** 0.5
                return dot_product / (mag1 * mag2) if (mag1 * mag2) > 0 else 0.0
        except Exception as e:
            # Если Ollama недоступна, делаем простое текстовое пересечение слов
            w1 = set(text1.lower().split())
            w2 = set(text2.lower().split())
            intersection = w1.intersection(w2)
            return len(intersection) / max(len(w1.union(w2)), 1)

    async def analyze_sync(self) -> dict:
        """Сквозной интеллектуальный анализ расхождений"""
        code_methods = self.scan_codebase()
        doc_bindings = self.scan_all_docs()
        
        documented_refs = {b["code_ref"] for b in doc_bindings}
        code_refs = set(code_methods.keys())
        
        # 1. Выявление рассинхронизаций (методы есть в доках, но удалены из кода)
        stale_bindings = []
        for binding in doc_bindings:
            ref = binding["code_ref"]
            if ref not in code_refs:
                stale_bindings.append({
                    "binding": binding,
                    "reason": "Метод изменен или полностью удален из кода"
                })
                
        # 2. Недокументированный код (методы есть в коде, но отсутствуют в code_ref XML)
        undocumented_methods = []
        for ref, data in code_methods.items():
            if ref not in documented_refs:
                # Запускаем интеллектуальный подбор подходящего раздела
                best_match_section = None
                best_score = 0.0
                
                for binding in doc_bindings:
                    # Сравниваем имя метода и заголовки разделов в XML
                    score = await self.calculate_semantic_similarity(
                        f"{data['name']} {data['docstring']}", 
                        binding["section_title"]
                    )
                    if score > best_score and score > 0.35: # Порог релевантности 35%
                        best_score = score
                        best_match_section = binding
                
                undocumented_methods.append({
                    "code_ref": ref,
                    "file": data["file"],
                    "method_name": data["name"],
                    "suggested_match": best_match_section,
                    "match_score": best_score
                })
                
        report = {
            "stale_bindings": stale_bindings,
            "undocumented_methods": undocumented_methods,
            "total_code_methods": len(code_methods),
            "total_documented_bindings": len(doc_bindings)
        }
        
        # Сохраняем результат в локальный json-стейт для UI
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
            
        return report
