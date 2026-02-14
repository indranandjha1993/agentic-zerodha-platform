import json
from collections.abc import Callable
from typing import Any, cast

from django.conf import settings
from openrouter import OpenRouter
from openrouter.components.chatmessagetoolcall import ChatMessageToolCall
from openrouter.components.chatresponse import ChatResponse

from apps.agents.models import Agent
from apps.agents.services.web_research_tools import (
    GoogleSearchTool,
    OpenWebpageTool,
    ResearchToolError,
)


class OpenRouterAgentError(RuntimeError):
    """Raised for OpenRouter agent runtime failures."""


class MissingLlmCredentialError(OpenRouterAgentError):
    """Raised when OPENROUTER_API_KEY is missing."""


class OpenRouterAgentCanceledError(OpenRouterAgentError):
    """Raised when analysis execution is canceled."""


class OpenRouterMarketAnalyst:
    def __init__(
        self,
        *,
        search_tool: GoogleSearchTool | None = None,
        webpage_tool: OpenWebpageTool | None = None,
    ) -> None:
        self.search_tool = search_tool or GoogleSearchTool()
        self.webpage_tool = webpage_tool or OpenWebpageTool()

    def analyze(
        self,
        *,
        agent: Agent,
        user_query: str,
        max_steps: int | None = None,
        model: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        api_key = str(getattr(settings, "OPENROUTER_API_KEY", "")).strip()
        if api_key == "":
            raise MissingLlmCredentialError(
                "OPENROUTER_API_KEY is not configured."
            )

        selected_model = (
            model
            or str(agent.config.get("openrouter_model", ""))
            or settings.OPENROUTER_DEFAULT_MODEL
        )
        steps = max(1, min(max_steps or settings.OPENROUTER_ANALYST_MAX_STEPS, 10))

        client = OpenRouter(
            api_key=api_key,
            http_referer=settings.OPENROUTER_HTTP_REFERER or None,
            x_title=settings.OPENROUTER_APP_TITLE or None,
            server_url=settings.OPENROUTER_BASE_URL,
        )

        system_prompt = (
            "You are a market research analyst for Indian equities. "
            "Use tools to gather recent company/market information before concluding. "
            "Summarize thesis, risks, catalysts, and data freshness."
        )
        messages: list[Any] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Agent instruction: {agent.instruction}\n\n"
                    f"Research request: {user_query}\n\n"
                    "Prefer concrete evidence and cite URLs from tool outputs."
                ),
            },
        ]

        tool_trace: list[dict[str, Any]] = []
        final_analysis = ""
        usage_payload: dict[str, Any] = {}
        self._emit_event(
            on_event,
            "analysis_started",
            {
                "model": selected_model,
                "max_steps": steps,
            },
        )

        for step_index in range(steps):
            if should_continue is not None and not should_continue():
                raise OpenRouterAgentCanceledError("Analysis run canceled by user.")
            self._emit_event(
                on_event,
                "llm_request",
                {"step": step_index + 1},
            )
            response = client.chat.send(
                model=selected_model,
                messages=cast(Any, messages),
                tools=cast(Any, self._tool_definitions()),
                tool_choice="auto",
                temperature=0.2,
            )
            if not isinstance(response, ChatResponse):
                raise OpenRouterAgentError("Unexpected OpenRouter response type.")

            if not response.choices:
                raise OpenRouterAgentError("OpenRouter returned no choices.")

            assistant_message = response.choices[0].message
            usage_payload = self._extract_usage(response)

            assistant_content = self._normalize_content(assistant_message.content)
            tool_calls = cast(list[ChatMessageToolCall], assistant_message.tool_calls or [])

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": [self._tool_call_to_payload(call) for call in tool_calls],
                    }
                )
                for tool_call in tool_calls:
                    self._emit_event(
                        on_event,
                        "tool_call",
                        {
                            "step": step_index + 1,
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    )
                    tool_result = self._execute_tool_call(tool_call)
                    tool_trace.append(tool_result)
                    self._emit_event(
                        on_event,
                        "tool_result",
                        {
                            "step": step_index + 1,
                            "tool_call_id": tool_result["tool_call_id"],
                            "tool_name": tool_result["tool_name"],
                            "result": tool_result["result"],
                        },
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_result["tool_call_id"],
                            "content": json.dumps(
                                tool_result["result"],
                                ensure_ascii=True,
                            ),
                        }
                    )
                continue

            final_analysis = assistant_content
            messages.append({"role": "assistant", "content": assistant_content})
            break

        if final_analysis.strip() == "":
            final_analysis = "No final analysis produced by the OpenRouter agent."

        result = {
            "status": "ok",
            "model": selected_model,
            "analysis": final_analysis,
            "tool_trace": tool_trace,
            "usage": usage_payload,
            "steps_executed": len(tool_trace),
        }
        self._emit_event(
            on_event,
            "analysis_completed",
            {
                "model": selected_model,
                "steps_executed": len(tool_trace),
                "usage": usage_payload,
            },
        )
        return result

    def _execute_tool_call(self, tool_call: ChatMessageToolCall) -> dict[str, Any]:
        tool_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments or "{}"
        parsed_arguments: dict[str, Any]
        result: Any
        try:
            parsed_arguments = cast(dict[str, Any], json.loads(raw_arguments))
        except json.JSONDecodeError:
            parsed_arguments = {}

        try:
            if tool_name == "google_search":
                query = str(parsed_arguments.get("query", "")).strip()
                limit = int(parsed_arguments.get("limit", 5))
                result = self.search_tool.search(query=query, limit=limit)
            elif tool_name == "open_webpage":
                url = str(parsed_arguments.get("url", "")).strip()
                max_chars = int(parsed_arguments.get("max_chars", 6000))
                result = self.webpage_tool.open(url=url, max_chars=max_chars)
            else:
                result = {"error": f"Unsupported tool: {tool_name}"}
        except (ResearchToolError, ValueError) as exc:
            result = {"error": str(exc)}

        return {
            "tool_call_id": tool_call.id,
            "tool_name": tool_name,
            "arguments": parsed_arguments,
            "result": result,
        }

    @staticmethod
    def _tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "google_search",
                    "description": (
                        "Search Google for market/company context and recent developments."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "open_webpage",
                    "description": "Open a public webpage and return cleaned textual content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
                        },
                        "required": ["url"],
                    },
                },
            },
        ]

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    chunks.append(str(part["text"]))
                else:
                    chunks.append(str(part))
            return "\n".join(chunks).strip()
        return str(content or "")

    @staticmethod
    def _tool_call_to_payload(tool_call: ChatMessageToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }

    @staticmethod
    def _extract_usage(response: ChatResponse) -> dict[str, Any]:
        usage = response.usage
        if usage is None:
            return {}

        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }

    @staticmethod
    def _emit_event(
        on_event: Callable[[str, dict[str, Any]], None] | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if on_event is None:
            return
        on_event(event_type, payload)
