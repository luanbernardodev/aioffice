"""Wrapper da API Anthropic com Prompt Caching e parser JSON tolerante."""
import json
import logging
import re
from typing import Any, Dict, Optional, Union

import anthropic

from config import settings

log = logging.getLogger("claude")


class ClaudeError(RuntimeError):
    """Falha na chamada ou no parsing da resposta do Claude."""


def extract_json(text: str) -> Dict[str, Any]:
    """Extrai o primeiro objeto JSON válido de um texto, com tolerância a markdown e truncamentos leves."""
    if not text:
        raise ClaudeError("Resposta vazia do modelo.")
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        candidate = cleaned[match.start():]
        try:
            obj, _ = decoder.raw_decode(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # Tentativa de reparo caso o output tenha sido truncado no final
        for suffix in ['"}', '"} ]}', '"}]}', '"]}', '}', '}}', '"']:
            try:
                repaired = candidate + suffix
                obj, _ = decoder.raw_decode(repaired)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    raise ClaudeError(f"Nenhum JSON válido encontrado na resposta: {text[:200]!r}")


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            log.warning("ANTHROPIC_API_KEY ausente: chamadas ao Claude vão falhar.")
        headers = ({"anthropic-workspace-id": settings.ANTHROPIC_WORKSPACE_ID}
                   if settings.ANTHROPIC_WORKSPACE_ID else None)
        self.client = anthropic.Anthropic(api_key=key or None, max_retries=3, default_headers=headers)
        self.cache_stats = {"calls": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def ask_json(self, model: str, system_prompt: str, user_payload: Union[dict, list, str],
                 max_tokens: int = 2048) -> Dict[str, Any]:
        """Envia o system prompt com cache_control ephemeral e retorna o JSON parseado."""
        user_text = user_payload if isinstance(user_payload, str) else json.dumps(
            user_payload, ensure_ascii=False, default=str)
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_text}],
            )
        except Exception as exc:  # noqa: BLE001
            raise ClaudeError(f"Erro na API Anthropic ({model}): {exc}") from exc

        usage = getattr(response, "usage", None)
        self.cache_stats["calls"] += 1
        if usage:
            self.cache_stats["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            self.cache_stats["cache_write_tokens"] += getattr(usage, "cache_creation_input_tokens", 0) or 0

        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        return extract_json(text)

    def ask_text(self, model: str, prompt: str, max_tokens: int = 256) -> str:
        """Envia um prompt de texto simples e retorna a resposta como string."""
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        except Exception as exc:  # noqa: BLE001
            raise ClaudeError(f"Erro na API Anthropic ({model}): {exc}") from exc

    def ask_with_tools(self, model: str, system_prompt: str, initial_user_message: str,
                       tools: List[Dict[str, Any]], tool_executor: Any,
                       max_turns: int = 5, max_tokens: int = 2048) -> Dict[str, Any]:
        """Loop autônomo de Tool Use com o Claude:
        Claude invoca ferramentas MCP repetidamente e, ao concluir a investigação, retorna o JSON final parseado.
        """
        messages = [{"role": "user", "content": initial_user_message}]

        for turn in range(max_turns):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": system_prompt,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:  # noqa: BLE001
                raise ClaudeError(f"Erro na API Anthropic durante Tool Use ({model}): {exc}") from exc

            # Se Claude decidiu usar uma ou mais ferramentas MCP
            if getattr(response, "stop_reason", "") == "tool_use":
                assistant_content = response.content
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if getattr(block, "type", "") == "tool_use":
                        t_name = getattr(block, "name", "")
                        t_input = getattr(block, "input", {})
                        t_id = getattr(block, "id", "")
                        log.info("[Claude Tool Use] Investigando via MT5 MCP: %s com params: %s", t_name, t_input)
                        try:
                            result = tool_executor(t_name, t_input)
                        except Exception as tool_err:
                            result = {"error": str(tool_err)}

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": t_id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                # Turno final: extrai o texto do bloco de resposta e faz o parse do JSON
                text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
                return extract_json(text)

        raise ClaudeError("Limite de turnos excedido sem resposta final do Claude.")
