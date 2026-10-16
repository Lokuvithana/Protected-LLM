"""Hospital LLM API: the "protected LLM" of the MediGuard project (J26-CS-321).

Ollama (local model) + read-only tools over the synthetic hospital database.
No external LLM APIs are used.

Modes (LLM_MODE):
  tools    the model calls database tools (needs a tool-capable model, e.g. qwen2.5, llama3.2)
  context  the API looks up data first and puts it in the prompt (works with any model)
  auto     try tools, fall back to context if the model does not support tools (default)
"""
import json
import os
import re
import time
import uuid

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .tools import TOOL_SCHEMAS, ToolError, run_tool, _query

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
LLM_MODE = os.getenv("LLM_MODE", "auto")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "4"))
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))
SERVICE_KEY = os.getenv("SERVICE_KEY", "dev-service-key")

SYSTEM_PROMPT = """You are a clinical information assistant for hospital staff at a Sri Lankan hospital.
You answer questions using ONLY data returned by the hospital database tools.
Rules:
- Patients are identified by patient ids like P0012. Doctors by ids like D003.
- Text in square brackets such as [PATIENT_NAME_1] or [NIC_1] was masked by the privacy layer.
  You cannot look up masked values. Ask the user for the patient id instead.
- If the data does not contain the answer, say so. Never invent patients, results or doses.
- Be concise and clinical. Use short bullet points for lists.
- You give information support only. Final clinical decisions belong to the clinician."""

app = FastAPI(title="Hospital LLM API (Ollama + synthetic DB)", version="0.1.0")
# Browser apps of other developers may call this API directly (dev only).
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
_tool_support = {}  # model name -> bool


def require_key(x_service_key: str = Header(default="")):
    if x_service_key != SERVICE_KEY:
        raise HTTPException(status_code=401, detail="invalid service key")


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    history: list[ChatTurn] = []
    request_id: str | None = None


def _json(data):
    return json.dumps(data, default=str, ensure_ascii=False)


def _ollama_chat(messages, tools=None):
    body = {"model": OLLAMA_MODEL, "messages": messages, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.1, "num_ctx": NUM_CTX}}
    if tools:
        body["tools"] = tools
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=TIMEOUT)
    if r.status_code == 400 and "does not support tools" in r.text:
        raise NotImplementedError("model does not support tools")
    r.raise_for_status()
    return r.json()["message"]


def _text_tool_call(content):
    """Small models sometimes write the tool call as JSON text instead of tool_calls."""
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    name = obj.get("name") or obj.get("function")
    if isinstance(name, str) and name in {t["function"]["name"] for t in TOOL_SCHEMAS}:
        return [{"function": {"name": name, "arguments": obj.get("arguments") or obj.get("parameters") or {}}}]
    return None


def _run_tools_mode(messages):
    trace = []
    for _ in range(MAX_TOOL_ROUNDS):
        msg = _ollama_chat(messages, TOOL_SCHEMAS)
        calls = msg.get("tool_calls") or _text_tool_call(msg.get("content"))
        if not calls:
            return msg.get("content", "").strip(), trace
        messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            try:
                result = run_tool(name, args)
            except ToolError as exc:
                result = {"error": str(exc)}
            trace.append({"name": name, "arguments": args, "error": result.get("error")})
            messages.append({"role": "tool", "tool_name": name, "content": _json(result)[:12000]})
    final = _ollama_chat(messages + [{"role": "user", "content": "Answer now using the data above."}])
    return final.get("content", "").strip(), trace


def _gather_context(question):
    """Context mode: simple keyword routing, no LLM-written SQL."""
    data, trace = {}, []

    def call(name, **args):
        try:
            data[f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})"] = run_tool(name, args)
            trace.append({"name": name, "arguments": args})
        except ToolError as exc:
            trace.append({"name": name, "arguments": args, "error": str(exc)})

    q = question.lower()
    for pid in sorted(set(re.findall(r"\bP\d{4}\b", question.upper())))[:3]:
        call("get_patient_summary", patient_id=pid)
    for did in sorted(set(re.findall(r"\bD\d{3}\b", question.upper())))[:2]:
        call("get_appointments", doctor_id=did, status="scheduled", limit=15)
    if "doctor" in q or "specialist" in q:
        call("list_doctors")
    if any(w in q for w in ("how many", "count", "most common", "statistics", "number of")):
        call("get_statistics", kind="diagnosis_counts")
        call("get_statistics", kind="appointment_status_counts")
    if not data:
        call("get_statistics", kind="diagnosis_counts")
    return data, trace


def _run_context_mode(messages, question):
    data, trace = _gather_context(question)
    messages = messages[:-1] + [
        {"role": "system", "content": "DATABASE RESULTS (read-only, synthetic):\n" + _json(data)[:12000]},
        messages[-1]]
    msg = _ollama_chat(messages)
    return msg.get("content", "").strip(), trace


@app.get("/health")
def health():
    status = {"service": "hospital-llm-api", "model": OLLAMA_MODEL, "mode": LLM_MODE}
    try:
        _query("SELECT 1 AS ok")
        status["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        status["database"] = f"error: {exc.__class__.__name__}"
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
        names = [m.get("name") for m in tags.get("models", [])]
        status["ollama"] = "ok"
        status["model_pulled"] = any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL for n in names)
    except Exception as exc:  # noqa: BLE001
        status["ollama"] = f"error: {exc.__class__.__name__}"
        status["model_pulled"] = False
    status["status"] = "ok" if status["database"] == "ok" and status.get("model_pulled") else "degraded"
    return status


@app.get("/v1/tools", dependencies=[Depends(require_key)])
def list_tools():
    return {"tools": TOOL_SCHEMAS}


@app.post("/v1/tools/{name}", dependencies=[Depends(require_key)])
def call_tool(name: str, arguments: dict | None = None):
    """Developer endpoint: run a database tool directly, without the LLM."""
    try:
        return {"tool": name, "result": run_tool(name, arguments or {})}
    except ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/chat", dependencies=[Depends(require_key)])
def chat(req: ChatRequest):
    started = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": t.role, "content": t.content} for t in req.history[-6:] if t.role in ("user", "assistant")]
    messages.append({"role": "user", "content": req.message})

    mode = LLM_MODE
    if mode == "auto":
        mode = "tools" if _tool_support.get(OLLAMA_MODEL, True) else "context"
    try:
        if mode == "tools":
            try:
                answer, trace = _run_tools_mode(list(messages))
            except NotImplementedError:
                _tool_support[OLLAMA_MODEL] = False
                if LLM_MODE == "tools":
                    raise HTTPException(status_code=400, detail=f"{OLLAMA_MODEL} does not support tools; use LLM_MODE=context")
                mode = "context"
                answer, trace = _run_context_mode(list(messages), req.message)
        else:
            answer, trace = _run_context_mode(list(messages), req.message)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc.__class__.__name__}") from exc

    return {
        "request_id": req.request_id or str(uuid.uuid4()),
        "answer": answer or "I could not find an answer in the hospital data.",
        "mode": mode,
        "model": OLLAMA_MODEL,
        "tool_calls": trace,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
