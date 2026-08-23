"""
Drafting-Assistant v2: реальный вызов Ollama/Qwen2.5 для черновика
актуализации устаревшего раздела документации.
Issue #9.
"""
import json
import httpx
import config

FALLBACK_TEMPLATE = (
    "<!-- TODO(doc-sync): раздел устарел — code_ref '{code_ref}' "
    "изменён или удалён из кода. Актуализируйте текст ниже. -->\n"
)

SYSTEM_PROMPT = (
    "Ты — технический писатель. Тебе дают diff кода и текущий текст "
    "раздела документации, который на этот код ссылается. Предложи "
    "короткий черновик обновлённого текста раздела на русском языке. "
    "Отвечай СТРОГО в формате JSON без пояснений вокруг: "
    '{"draft_text": "...", "confidence": 0.0-1.0}. '
    "confidence — твоя уверенность, что draft_text корректно "
    "отражает изменения."
)


class DraftingAssistant:
    """Генерирует черновик обновлённого текста раздела через Ollama."""

    def __init__(self, retries: int = 3, timeout: float = 30.0):
        self.retries = retries
        self.timeout = timeout
        self.url = f"{config.OLLAMA_HOST}/api/generate"

    def _build_prompt(self, code_diff: str, current_section_text: str) -> str:
        return (
            f"### Diff кода (code_ref изменён/удалён)\n{code_diff}\n\n"
            f"### Текущий текст раздела документации\n{current_section_text}\n\n"
            "Предложи обновлённый текст раздела."
        )

    async def generate_draft(
        self, binding: dict, current_section_text: str, code_diff: str = ""
    ) -> dict:
        """Возвращает {"draft_text": str, "confidence": float, "fallback": bool}.
        При ошибке/недоступности Ollama после retries попыток — fallback
        на статичный TODO-шаблон (confidence=0.0, fallback=True)."""
        diff = code_diff or f"Метод '{binding['code_ref']}' изменён или удалён из кода."
        prompt = self._build_prompt(diff, current_section_text)
        payload = {
            "model": config.OLLAMA_MODEL,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }

        last_err = None
        for _ in range(self.retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(self.url, json=payload)
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

        print(f"[drafting_assistant] Ollama недоступна/ошибка после "
              f"{self.retries} попыток: {last_err}. Fallback на TODO-шаблон.")
        return {
            "draft_text": FALLBACK_TEMPLATE.format(code_ref=binding["code_ref"]),
            "confidence": 0.0,
            "fallback": True,
        }
