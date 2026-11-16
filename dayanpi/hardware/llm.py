"""Asks a small model running in Ollama on the Pi for a short text. The only thing here that talks to Ollama.

It only ever calls http://127.0.0.1:11434. The host is fixed, and http.client goes
straight to it: no proxy settings, no redirects. DAYANPI_LLM_MODEL (like llama3.2:1b)
turns it on; unset means no LLM. Setup is in docs/voice.md.
"""

import http.client
import json
import os
from collections.abc import Mapping

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
LLM_MODEL_ENV = "DAYANPI_LLM_MODEL"

LLM_THREADS = 2  # leaves the other cores to the focus checks
KEEP_ALIVE = "15m"  # longer than the gap between calls, so the model stays loaded
TIMEOUT_S = 60.0  # about 11 tokens a second on the Pi, plus loading the model the first time
MAX_TOKENS = 120  # 4 short sentences fit in well under this
TEMPERATURE = 0.7


def read_llm_model(environ: Mapping[str, str] = os.environ) -> str | None:
    model = environ.get(LLM_MODEL_ENV, "").strip() or None
    return model


class OllamaClient:
    def __init__(self, model: str, port: int = OLLAMA_PORT, timeout_s: float = TIMEOUT_S) -> None:
        self.model = model
        self._port = port
        self._timeout_s = timeout_s
        self.problem: str | None = None  # why the last call gave nothing, for the log

    def generate(self, system: str, prompt: str) -> str | None:
        """The model's reply, or None when Ollama isn't running, times out or answers with an error."""
        body = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_thread": LLM_THREADS, "num_predict": MAX_TOKENS, "temperature": TEMPERATURE},
        }
        reply = None
        connection = http.client.HTTPConnection(OLLAMA_HOST, self._port, timeout=self._timeout_s)
        try:
            connection.request("POST", "/api/generate", body=json.dumps(body), headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = json.loads(response.read() or b"{}")
            reply = data.get("response") if response.status == 200 else None
            self.problem = None if isinstance(reply, str) else f"Ollama said {response.status}: {data.get('error', 'no reply')}"
        except (OSError, http.client.HTTPException, ValueError, AttributeError) as error:  # AttributeError: JSON that isn't an object
            self.problem = f"{type(error).__name__}: {error}"
        finally:
            connection.close()
        text = reply if isinstance(reply, str) else None
        return text
