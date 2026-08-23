"""
agents.py — ИИ-агенты Doc-as-Code Copilot v2 поверх LangGraph StateGraph
(см. graph-v2.py). Базовый AIAgent + 4 роли; DraftingAssistantAgent
реализует Issue #9 — реальный вызов Ollama/Qwen2.5 со structured output.
"""
import json
import httpx
import config_sync as config


class AIAgent:
    """Базовый класс ИИ-агента, взаимодействующего с локальной LLM Ollama"""

    def __init__(self, name: str, role: str, system_prompt: str):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt

    async def chat(self, prompt: str, temperature: float = 0.1) -> str:
        """Запрос к Ollama /api/chat (для агентов, которым не нужен строгий JSON)."""
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": f"{self.system_prompt}\nВаша роль: {self.role}"},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"{config.OLLAMA_HOST}/api/chat", json=payload)
                r.raise_for_status()
                return r.json()["message"]["content"]
        except Exception as e:
            print(f"[Agent {self.name} Error]: {e}")
            return (
                "[Внимание: Ошибка LLM, применен локальный генератор шаблонов]\n\n"
                "TODO: Проверить метод в коде. Изменения требуют ручной валидации."
            )


class ASTDetectiveAgent(AIAgent):
    """Агент-Детектив: анализирует синтаксические деревья кода и объясняет изменения"""

    def __init__(self):
        super().__init__(
            name="AST-Detective",
            role="Ведущий системный программист",
            system_prompt=(
                "Вы — высококлассный системный архитектор. Проанализируйте "
                "предоставленный diff кода Python и извлеките суть изменений: "
                "какой метод изменился, какие параметры затронуты, какой "
                "бизнес-смысл несут изменения. Отвечайте кратко и структурированно."
            ),
        )

    async def analyze_diff(self, filename: str, method_name: str, diff_text: str) -> str:
        prompt = (
            f"Файл: {filename}\nМетод: {method_name}\n"
            f"Diff изменений:\n```diff\n{diff_text}\n```\n\n"
            "Объясни кратко и технически грамотно, что изменилось и почему "
            "это влияет на логику работы."
        )
        return await self.chat(prompt, temperature=0.1)


class XMLNavigatorAgent(AIAgent):
    """Агент-Навигатор: сверяет разделы XML и находит связи с кодом"""

    def __init__(self):
        super().__init__(
            name="XML-Navigator",
            role="Старший технический писатель по стандартам DocBook XML",
            system_prompt=(
                "Вы — эксперт по XML-документации (упрощённый DocBook). "
                "Сопоставляйте разделы <section> с изменениями в коде по "
                "атрибуту code_ref и точно определяйте устаревшие разделы."
            ),
        )

    def find_target_section(self, xml_content: str, code_ref: str) -> dict | None:
        from lxml import etree
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.fromstring(xml_content.encode("utf-8"), parser)
            sec = root.xpath(f"//section[@code_ref='{code_ref}']")
            if sec:
                title_node = sec[0].find("title")
                title = title_node.text if title_node is not None else "Без заголовка"
                return {
                    "id": sec[0].get("id"),
                    "title": title,
                    "xpath": root.getroottree().getpath(sec[0]),
                }
        except Exception as e:
            print(f"[Error in XML parsing]: {e}")
        return None

    def extract_section_xml(self, xml_content: str, section_id: str) -> str:
        """Возвращает XML текущего раздела по id (для промпта Drafting-Assistant)."""
        from lxml import etree
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.fromstring(xml_content.encode("utf-8"), parser)
            sec = root.xpath(f'//section[@id="{section_id}"]')
            if sec:
                return etree.tostring(sec[0], pretty_print=True, encoding="unicode")
        except Exception as e:
            print(f"[Error in XML parsing]: {e}")
        return ""


DRAFT_SYSTEM_PROMPT = (
    "Вы — технический писатель. Вам дают diff кода (что изменилось в методе, "
    "на который ссылается раздел) и текущий текст XML-раздела документации. "
    "Предложите короткий черновик обновлённого текста раздела на русском "
    "языке. Отвечайте СТРОГО в формате JSON без пояснений вокруг: "
    '{"draft_text": "...", "confidence": 0.0-1.0}. confidence — ваша '
    "уверенность, что draft_text корректно отражает изменения."
)

DRAFT_FALLBACK_TEMPLATE = (
    "<!-- TODO (ИИ): раздел устарел — метод '{method_name}' изменён или "
    "удалён из кода. Актуализируйте текст ниже вручную. -->"
)


class DraftingAssistantAgent(AIAgent):
    """Агент-Редактор (Issue #9): реальный вызов Ollama/Qwen2.5 через
    /api/generate со structured output {draft_text, confidence}, retry и
    fallback на TODO-шаблон при ошибке/недоступности LLM."""

    def __init__(self, retries: int = 3, timeout: float = 30.0):
        super().__init__(
            name="Drafting-Assistant",
            role="Технический писатель и ИИ-редактор",
            system_prompt=DRAFT_SYSTEM_PROMPT,
        )
        self.retries = retries
        self.timeout = timeout

    async def generate_draft(self, method_name: str, current_section_xml: str, code_diff: str = "") -> dict:
        """Возвращает {"draft_text": str, "confidence": float, "fallback": bool}."""
        diff = code_diff or f"Метод '{method_name}' изменён или удалён из кода."
        prompt = (
            f"### Diff кода\n{diff}\n\n"
            f"### Текущий текст раздела документации\n{current_section_xml}\n\n"
            "Предложи обновлённый текст раздела."
        )
        payload = {
            "model": config.OLLAMA_MODEL,
            "system": self.system_prompt,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }

        last_err = None
        for _ in range(self.retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(f"{config.OLLAMA_HOST}/api/generate", json=payload)
                    r.raise_for_status()
                    parsed = json.loads(r.json()["response"])
                    draft_text = str(parsed["draft_text"]).strip()
                    if not draft_text:
                        raise ValueError("Пустой draft_text от модели")
                    confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
                    return {"draft_text": draft_text, "confidence": confidence, "fallback": False}
            except Exception as e:
                last_err = e
                continue

        print(
            f"[{self.name}] Ollama недоступна/ошибка после {self.retries} "
            f"попыток: {last_err}. Fallback на TODO-шаблон."
        )
        return {
            "draft_text": DRAFT_FALLBACK_TEMPLATE.format(method_name=method_name),
            "confidence": 0.0,
            "fallback": True,
        }

    async def generate_xml_todo(self, section_title: str, method_name: str, changes_summary: str) -> str:
        """Обратная совместимость с прежним узким вызовом (без current_section_xml/
        structured output) — используется как крайний fallback вне generate_draft."""
        prompt = (
            "Сгенерируй профессиональный TODO-комментарий для технического "
            f'писателя.\nРаздел документации: "{section_title}"\n'
            f'Изменившийся метод кода: "{method_name}"\n'
            f"Что изменилось в коде: {changes_summary}\n\n"
            "Напиши точный XML-комментарий (строго на русском языке). "
            "Ответ должен содержать только сам комментарий в формате "
            "`<!-- TODO (ИИ): ... -->`."
        )
        return await self.chat(prompt, temperature=0.2)


class DevOpsCoordinatorAgent(AIAgent):
    """Агент-Координатор: формирует описания GitHub Issue/PR"""

    def __init__(self):
        super().__init__(
            name="DevOps-Coordinator",
            role="DevOps-инженер и менеджер релизов",
            system_prompt=(
                "Вы — DevOps-инженер. Формируйте описания Pull Request, "
                "отчёты для GitHub Issues и понятные коммит-сообщения "
                "(Conventional Commits)."
            ),
        )

    async def generate_issue_body(self, stale_sections: list) -> str:
        sections_str = json.dumps(stale_sections, ensure_ascii=False, indent=2)
        prompt = (
            "Сформируй детальный отчёт для GitHub Issue.\n"
            f"Список устаревших разделов документации:\n{sections_str}\n\n"
            "Отчёт на русском: суть проблемы, таблица устаревших файлов/"
            "разделов/методов, шаги по исправлению для техписателя. Markdown."
        )
        return await self.chat(prompt, temperature=0.1)
