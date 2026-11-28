"""Model providers for the LLM judge, behind one small interface so models can be swapped.

Every provider takes a system prompt and a user prompt and returns the model's text.
Any failure raises ProviderError, which the judge turns into a safe fallback.

- OllamaProvider: a model served by Ollama, usually on this machine.
- OpenAICompatibleProvider: any server with an OpenAI-style /chat/completions route,
  such as vLLM or llama.cpp. API keys are read from an environment variable, never code.
- TransformersProvider: runs a Hugging Face model in this process, for Kaggle.
  Needs torch and transformers, which are not project dependencies.

provider_from_env() builds one from LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL and
LLM_API_KEY_ENV, so the scoring command can switch models without code changes.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

try:
    from typing import Protocol
except ImportError:  # Python 3.7
    Protocol = object


class ProviderError(RuntimeError):
    """The model could not be reached or did not answer."""


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


def _post_json(url: str, payload: dict, timeout: float, headers: Optional[dict] = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ProviderError(f"{url}: {type(error).__name__}: {error}") from error


class OllamaProvider:
    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: float = 60):
        self.name = f"ollama:{model}"
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout

    def complete(self, system: str, user: str) -> str:
        reply = _post_json(f"{self.base_url}/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }, self.timeout)
        try:
            return reply["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ProviderError(f"Unexpected Ollama response: {str(reply)[:200]}") from error


class OpenAICompatibleProvider:
    def __init__(self, model: str, base_url: str, api_key: Optional[str] = None, timeout: float = 60, json_mode: bool = True):
        self.name = f"openai-compatible:{model}"
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.api_key, self.json_mode = api_key, json_mode

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        reply = _post_json(f"{self.base_url}/chat/completions", payload, self.timeout, headers)
        try:
            return reply["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(f"Unexpected response: {str(reply)[:200]}") from error


class TransformersProvider:
    """Runs a chat model in this process. Loads it on first use."""

    def __init__(self, model: str, max_new_tokens: int = 300):
        self.name = f"transformers:{model}"
        self.model_id, self.max_new_tokens = model, max_new_tokens
        self._model = self._tokenizer = None

    def _load(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise ProviderError("TransformersProvider needs torch and transformers installed.") from error
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForCausalLM.from_pretrained(self.model_id, torch_dtype=torch.float16, device_map="auto")
        self._model.eval()

    def complete(self, system: str, user: str) -> str:
        if self._model is None:
            self._load()
        import torch

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        try:
            with torch.inference_mode():
                output = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        except RuntimeError as error:
            raise ProviderError(f"Generation failed: {error}") from error
        return self._tokenizer.decode(output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)


def provider_from_env(environ=None) -> Provider:
    environ = os.environ if environ is None else environ
    kind = environ.get("LLM_PROVIDER", "").strip().lower()
    model = environ.get("LLM_MODEL", "").strip()
    timeout = float(environ.get("LLM_TIMEOUT", "60"))
    if not kind or not model:
        raise ProviderError("Set LLM_PROVIDER (ollama, openai, transformers) and LLM_MODEL.")
    if kind == "ollama":
        return OllamaProvider(model, environ.get("LLM_BASE_URL", "http://localhost:11434"), timeout)
    if kind == "openai":
        base_url = environ.get("LLM_BASE_URL", "").strip()
        if not base_url:
            raise ProviderError("Set LLM_BASE_URL for an OpenAI-compatible server.")
        key_name = environ.get("LLM_API_KEY_ENV", "").strip()
        return OpenAICompatibleProvider(model, base_url, environ.get(key_name) if key_name else None, timeout)
    if kind == "transformers":
        return TransformersProvider(model)
    raise ProviderError(f"Unknown LLM_PROVIDER {kind!r}.")
