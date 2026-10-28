"""The model: one chat-completions call with tools against any OpenAI-compatible endpoint."""
import asyncio

import httpx

SAMPLING = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repetition_penalty")


class LLM:
    def __init__(self, base_url, api_key, model, on_error=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self.on_error = on_error or (lambda **kw: None)
        # Local servers load a model on the first request (30-120 s) and long prompts take time.
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=30))
        self.usage = {"prompt": 0, "completion": 0, "last_prompt": 0, "calls": 0}

    async def chat(self, messages, tools):
        m = self.model
        body = {"model": m["id"], "messages": messages, "max_tokens": m["max_tokens"]}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        body.update({k: m[k] for k in SAMPLING if k in m})
        for attempt in range(4):
            try:
                r = await self.http.post(self.url, json=body, headers=self.headers)
                r.raise_for_status()
                data = r.json()
                break
            except httpx.HTTPError as e:
                detail = getattr(getattr(e, "response", None), "text", "")[:500]
                self.on_error(error=str(e), detail=detail, attempt=attempt)
                if attempt == 3:
                    raise RuntimeError(f"model endpoint failed 4 times: {e} {detail}") from e
                await asyncio.sleep(10 * (attempt + 1))
        u = data.get("usage") or {}
        self.usage["prompt"] += u.get("prompt_tokens", 0)
        self.usage["completion"] += u.get("completion_tokens", 0)
        self.usage["last_prompt"] = u.get("prompt_tokens", 0)
        self.usage["calls"] += 1
        choice = data["choices"][0]
        return choice["message"], choice.get("finish_reason"), u

    async def close(self):
        await self.http.aclose()
