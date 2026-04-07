"""
Streaming LLM client for the embedded chat side panel.

Supports Anthropic (direct), AWS Bedrock, and OpenAI providers.
Runs the full agentic tool loop: text → tool_call → tool_result → text → ...

Yields SSE-formatted strings that the ChatStreamV2View sends to the browser.
The event names match what chat_interface.html's EventSource handlers expect:
    text        — partial assistant text chunk
    tool_call   — {tool, status}  (status: 'running' | 'done' | 'error')
    done        — {conversation_id}
    error       — {message}
"""
import json
import logging
import os
from typing import Any, Generator, Optional

from django.conf import settings

from mcp_server.tools import TOOL_DEFINITIONS, execute_tool, ToolError
from .librechat_config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_BEDROCK,
    PROVIDER_OPENAI,
    PROVIDER_OPENROUTER,
)

logger = logging.getLogger(__name__)

# Max agentic loop iterations to prevent runaway calls
MAX_TOOL_ROUNDS = 10

# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Content block serialization ──────────────────────────────────────────────

def _serialize_content(content) -> list[dict]:
    """Convert Anthropic SDK content blocks to plain dicts for API messages.

    SDK objects (TextBlock, ToolUseBlock) carry internal attributes like `caller`
    that the API rejects. Only include the fields the API actually expects.
    """
    result = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            result.append({"type": "text", "text": block.text})
        elif btype == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


# ── Tool schema conversion ────────────────────────────────────────────────────

def _tools_for_anthropic() -> list[dict]:
    """Convert MCP TOOL_DEFINITIONS to Anthropic SDK format."""
    result = []
    for t in TOOL_DEFINITIONS:
        schema = dict(t["inputSchema"])
        result.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": schema,
        })
    return result


def _tools_for_openai() -> list[dict]:
    """Convert MCP TOOL_DEFINITIONS to OpenAI function-calling format."""
    result = []
    for t in TOOL_DEFINITIONS:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["inputSchema"],
            },
        })
    return result


# ── Message history helpers ───────────────────────────────────────────────────

def _build_history(db_messages) -> list[dict]:
    """
    Convert a message list to API message format (Anthropic/OpenAI).

    Accepts either:
    - Django ChatMessage model instances  (msg.role / msg.content)
    - Plain dicts from ES                 (msg['role'] / msg['content'])
    """
    history = []
    for msg in db_messages:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content", "")
        else:
            role = msg.role
            content = msg.content
        if role == "user":
            history.append({"role": "user", "content": content})
        else:
            history.append({"role": "assistant", "content": content or ""})
    return history


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(project, page_context: Optional[dict]) -> str:
    base = (
        "You are Ask CodePathfinder, a friendly and enthusiastic helper embedded inside the CodePathfinder "
        "platform. Your job is to help users navigate and get the most out of CodePathfinder — whether "
        "that means managing projects, discovering skills, organizing memories, or searching code. "
        "Always respond with a positive, encouraging tone. Celebrate what the user is doing and "
        "make them feel capable and supported. "
        "You have access to tools for searching code, managing GitHub issues, working with skills, "
        "managing memories, and controlling indexing jobs. "
        "When you perform an action on behalf of the user (create/update/delete), confirm it warmly. "
        "Use tools proactively — if a tool would answer the question better than text alone, use it. "
        "Keep responses concise and actionable."
    )

    if project:
        base += f"\n\nCurrent project: {project.name} (ID: {project.id})"
        if hasattr(project, "github_url") and project.github_url:
            base += f"\nRepository: {project.github_url}"

    if page_context:
        page_name = page_context.get("page", "")
        items = page_context.get("items", [])
        actions = page_context.get("actions", [])
        url_path = page_context.get("url_path", "")
        url = page_context.get("url", "")

        base += f"\n\nThe user is currently on the {page_name} page"
        if url_path:
            base += f" (path: {url_path})"
        base += "."
        if url:
            base += f"\nFull URL: {url}"
        if items:
            import json as _json
            base += f"\nVisible items on this page: {_json.dumps(items[:20])}"
        if actions:
            base += f"\nAvailable actions on this page: {', '.join(actions)}"
        base += (
            "\nTailor your suggestions and responses to what is relevant on this page. "
            "When users ask to create, edit, or delete items, use the appropriate tools "
            "rather than just giving instructions."
        )

    return base


# ── Streaming implementations ─────────────────────────────────────────────────

def stream_anthropic(
    messages: list[dict],
    model_id: str,
    system: str,
    user,
) -> Generator[str, None, str]:
    """
    Stream via direct Anthropic API. Returns final assistant text as generator return value.
    """
    try:
        import anthropic
    except ImportError:
        yield _sse("error", {"message": "Anthropic SDK not installed. Run: pip install anthropic"})
        return ""

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        yield _sse("error", {"message": "ANTHROPIC_API_KEY not configured"})
        return ""

    client = anthropic.Anthropic(api_key=api_key)
    tools = _tools_for_anthropic()
    full_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        current_text = ""
        tool_calls_this_round = []
        with client.messages.stream(
            model=model_id,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                etype = type(event).__name__

                # TextEvent is the high-level text chunk emitted by the SDK stream
                if etype == "TextEvent":
                    chunk = event.text
                    current_text += chunk
                    full_text += chunk
                    yield _sse("text", chunk)

                # RawContentBlockStartEvent signals a new content block; detect tool_use here
                elif etype == "RawContentBlockStartEvent":
                    block = event.content_block
                    if getattr(block, "type", "") == "tool_use":
                        tool_calls_this_round.append({
                            "id": block.id,
                            "name": block.name,
                            "input": {},
                        })
                        yield _sse("tool_call", {"tool": block.name, "status": "running"})

            # Get final message to access complete tool inputs
            final_msg = stream.get_final_message()

        # Collect tool use blocks from final message
        tool_use_blocks = [b for b in final_msg.content if getattr(b, "type", "") == "tool_use"]

        if not tool_use_blocks:
            break  # No tools called — we're done

        # Execute tools and feed results back
        tool_results = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_args = block.input or {}
            try:
                result = execute_tool(tool_name, tool_args, user=user)
                yield _sse("tool_call", {"tool": tool_name, "status": "done"})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })
            except ToolError as e:
                logger.warning("Tool %s failed: %s", tool_name, e)
                yield _sse("tool_call", {"tool": tool_name, "status": "error"})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        # Append assistant turn + tool results for next iteration
        messages = messages + [
            {"role": "assistant", "content": _serialize_content(final_msg.content)},
            {"role": "user", "content": tool_results},
        ]

    return full_text


def stream_bedrock(
    messages: list[dict],
    model_id: str,
    system: str,
    user,
) -> Generator[str, None, str]:
    """Stream via AWS Bedrock using anthropic SDK with bedrock transport."""
    try:
        import anthropic
    except ImportError:
        yield _sse("error", {"message": "Anthropic SDK not installed. Run: pip install anthropic"})
        return ""

    try:
        import boto3
    except ImportError:
        yield _sse("error", {"message": "boto3 not installed. Run: pip install boto3"})
        return ""

    region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
    try:
        client = anthropic.AnthropicBedrock(aws_region=region)
    except Exception as e:
        yield _sse("error", {"message": f"Bedrock client error: {e}"})
        return ""

    tools = _tools_for_anthropic()
    full_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        with client.messages.stream(
            model=model_id,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                etype = type(event).__name__
                if etype == "TextEvent":
                    chunk = event.text
                    full_text += chunk
                    yield _sse("text", chunk)
                elif etype == "RawContentBlockStartEvent":
                    block = event.content_block
                    if getattr(block, "type", "") == "tool_use":
                        yield _sse("tool_call", {"tool": block.name, "status": "running"})

            final_msg = stream.get_final_message()

        tool_use_blocks = [b for b in final_msg.content if getattr(b, "type", "") == "tool_use"]
        if not tool_use_blocks:
            break

        tool_results = []
        for block in tool_use_blocks:
            try:
                result = execute_tool(block.name, block.input or {}, user=user)
                yield _sse("tool_call", {"tool": block.name, "status": "done"})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })
            except ToolError as e:
                yield _sse("tool_call", {"tool": block.name, "status": "error"})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        messages = messages + [
            {"role": "assistant", "content": _serialize_content(final_msg.content)},
            {"role": "user", "content": tool_results},
        ]

    return full_text


def stream_openai(
    messages: list[dict],
    model_id: str,
    system: str,
    user,
) -> Generator[str, None, str]:
    """Stream via OpenAI API with function calling."""
    try:
        from openai import OpenAI
    except ImportError:
        yield _sse("error", {"message": "OpenAI SDK not installed. Run: pip install openai"})
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        yield _sse("error", {"message": "OPENAI_API_KEY not configured"})
        return ""

    client = OpenAI(api_key=api_key)
    tools = _tools_for_openai()
    oai_messages = [{"role": "system", "content": system}] + messages
    full_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        stream = client.chat.completions.create(
            model=model_id,
            messages=oai_messages,
            tools=tools,
            stream=True,
        )

        current_text = ""
        tool_calls_acc: dict[int, dict] = {}  # index → {id, name, arguments}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                chunk_text = delta.content
                current_text += chunk_text
                full_text += chunk_text
                yield _sse("text", chunk_text)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                            yield _sse("tool_call", {"tool": tc.function.name, "status": "running"})
                    if tc.function:
                        if tc.function.name and not tool_calls_acc[idx]["name"]:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

        if not tool_calls_acc:
            break

        # Build assistant message with tool calls
        assistant_msg = {"role": "assistant", "content": current_text or None, "tool_calls": []}
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            assistant_msg["tool_calls"].append({
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })
        oai_messages.append(assistant_msg)

        # Execute tools
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                args = json.loads(tc["arguments"] or "{}")
                result = execute_tool(tc["name"], args, user=user)
                yield _sse("tool_call", {"tool": tc["name"], "status": "done"})
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })
            except Exception as e:
                yield _sse("tool_call", {"tool": tc["name"], "status": "error"})
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"Error: {e}",
                })

    return full_text


def stream_openrouter(
    messages: list[dict],
    model_id: str,
    system: str,
    user,
) -> Generator[str, None, str]:
    """Stream via OpenRouter (OpenAI-compatible) with function calling."""
    try:
        from openai import OpenAI
    except ImportError:
        yield _sse("error", {"message": "OpenAI SDK not installed. Run: pip install openai"})
        return ""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        yield _sse("error", {"message": "OPENROUTER_API_KEY not configured"})
        return ""

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    tools = _tools_for_openai()
    oai_messages = [{"role": "system", "content": system}] + messages
    full_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        stream = client.chat.completions.create(
            model=model_id,
            messages=oai_messages,
            tools=tools,
            stream=True,
        )

        current_text = ""
        tool_calls_acc: dict[int, dict] = {}  # index → {id, name, arguments}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                chunk_text = delta.content
                current_text += chunk_text
                full_text += chunk_text
                yield _sse("text", chunk_text)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                            yield _sse("tool_call", {"tool": tc.function.name, "status": "running"})
                    if tc.function:
                        if tc.function.name and not tool_calls_acc[idx]["name"]:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

        if not tool_calls_acc:
            break

        assistant_msg = {"role": "assistant", "content": current_text or None, "tool_calls": []}
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            assistant_msg["tool_calls"].append({
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })
        oai_messages.append(assistant_msg)

        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                args = json.loads(tc["arguments"] or "{}")
                result = execute_tool(tc["name"], args, user=user)
                yield _sse("tool_call", {"tool": tc["name"], "status": "done"})
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })
            except Exception as e:
                yield _sse("tool_call", {"tool": tc["name"], "status": "error"})
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"Error: {e}",
                })

    return full_text


# ── Public entry point ────────────────────────────────────────────────────────

def generate_stream(
    user_message: str,
    db_messages,
    model_config: dict,
    project,
    user,
    page_context: Optional[dict] = None,
) -> Generator[str, None, None]:
    """
    Main generator. Builds history, selects provider, streams SSE chunks.
    DB saving is handled by the caller (ChatStreamV2View).
    """
    provider = model_config["provider"]
    model_id = model_config["model_id"]
    system = _build_system_prompt(project, page_context)
    history = _build_history(db_messages)

    try:
        if provider == PROVIDER_ANTHROPIC:
            gen = stream_anthropic(history, model_id, system, user)
        elif provider == PROVIDER_BEDROCK:
            gen = stream_bedrock(history, model_id, system, user)
        elif provider == PROVIDER_OPENAI:
            gen = stream_openai(history, model_id, system, user)
        elif provider == PROVIDER_OPENROUTER:
            gen = stream_openrouter(history, model_id, system, user)
        else:
            yield _sse("error", {"message": f"Unknown provider: {provider}"})
            return

        for chunk in gen:
            yield chunk

    except Exception as e:
        logger.exception("Stream error for provider %s model %s", provider, model_id)
        yield _sse("error", {"message": str(e)})
        return
