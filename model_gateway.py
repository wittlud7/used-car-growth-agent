"""Server-only model configuration. Never return credentials to the browser or logs."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def credentials():
    key = os.getenv("AGENT_API_KEY", "")
    model = os.getenv("AGENT_MODEL", "")
    base = os.getenv("AGENT_API_BASE", "")
    source = "environment"
    path = Path(os.getenv("AGENT_SETTINGS_FILE", str(Path(__file__).resolve().parent.parent / "settings.json")))
    if not key and path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8-sig"))
            env = settings.get("env", {})
            key = env.get("ANTHROPIC_AUTH_TOKEN", "")
            model = model or env.get("ANTHROPIC_MODEL", "")
            base = base or env.get("ANTHROPIC_BASE_URL", "")
            source = "settings.json"
        except (ValueError, OSError, TypeError, AttributeError):
            return {"key": "", "model": "", "base": "", "provider": "", "source": "invalid_settings"}
    base = base or "https://api.deepseek.com"
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return {"key": "", "model": "", "base": "", "provider": "", "source": "invalid_endpoint"}
    provider = "deepseek" if parsed.hostname == "api.deepseek.com" else "compatible"
    if source == "settings.json" and provider != "deepseek":
        return {"key": "", "model": "", "base": "", "provider": "", "source": "unsupported_settings_endpoint"}
    if provider == "deepseek" and parsed.path.rstrip("/") in {"/anthropic", "/v1"}:
        base = "https://api.deepseek.com"
    return {"key": key if isinstance(key, str) else "", "model": model if isinstance(model, str) else "", "base": base.rstrip("/"), "provider": provider, "source": source}


def public_config():
    cfg = credentials()
    return {"ready": bool(cfg["key"] and cfg["model"]), "model": cfg["model"], "base": cfg["base"], "provider": cfg["provider"], "source": cfg["source"]}


def call_chat(messages, tools=None, max_tokens=1800):
    cfg = credentials()
    if not cfg["key"] or not cfg["model"]:
        raise RuntimeError("模型配置不可用，请检查本地 settings.json 或环境变量")
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "stream": False}
    if tools:
        body["tools"] = tools
    if cfg["provider"] == "deepseek":
        body["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(cfg["base"] + "/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["key"]}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        explanations = {401: "密钥无效", 402: "账户余额不足", 403: "无模型访问权限", 429: "请求过于频繁"}
        raise RuntimeError(f"模型服务HTTP {exc.code}：{explanations.get(exc.code, '请求未完成，请检查模型和服务配置')}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("模型服务连接失败或超时，请重试") from None
    except (ValueError, TypeError):
        raise RuntimeError("模型服务返回格式异常") from None


def responses_adapter(body):
    """Keep the earlier consultation Agent working with Chat Completions providers."""
    messages = []
    for item in body.get("input", []):
        kind = item.get("type")
        if kind == "function_call":
            call = {"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}}
            if messages and messages[-1].get("tool_calls") and messages[-1]["role"] == "assistant":
                messages[-1]["tool_calls"].append(call)
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
        elif item.get("role") in {"system", "user", "assistant"}:
            messages.append({"role": item["role"], "content": item.get("content", "")})
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in body.get("tools", [])]
    response = call_chat(messages, tools)
    msg = response["choices"][0]["message"]
    output = [{"type": "function_call", "call_id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in msg.get("tool_calls", [])]
    if msg.get("content"):
        output.append({"type": "message", "role": "assistant", "content": msg["content"]})
    u = response.get("usage", {})
    return {"output": output, "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}}
