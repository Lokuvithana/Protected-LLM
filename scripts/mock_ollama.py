"""A tiny fake Ollama for tests and CI (no model download, answers instantly).

It speaks the parts of the Ollama API the LLM API uses: /api/version, /api/tags,
/api/chat (with tool calls). Answers are canned, so use it to test plumbing,
never to judge answer quality.

    pip install fastapi uvicorn
    uvicorn scripts.mock_ollama:app --port 11434
"""
import json
import re

from fastapi import FastAPI, Request

app = FastAPI(title="mock-ollama")


@app.get("/api/version")
def version():
    return {"version": "mock"}


@app.get("/api/tags")
def tags():
    return {"models": [{"name": "qwen2.5:3b", "model": "qwen2.5:3b"}]}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    msgs = body.get("messages", [])
    last = msgs[-1] if msgs else {"role": "user", "content": ""}
    tools = body.get("tools")
    if tools and last["role"] == "user":
        text = last["content"]
        pid = re.search(r"\bP\d{4}\b", text)
        if pid:
            call = {"name": "get_patient_summary", "arguments": {"patient_id": pid.group(0)}}
        elif "doctor" in text.lower():
            call = {"name": "list_doctors", "arguments": {}}
        else:
            call = {"name": "get_statistics", "arguments": {"kind": "diagnosis_counts"}}
        return {"model": body.get("model"), "done": True,
                "message": {"role": "assistant", "content": "", "tool_calls": [{"function": call}]}}
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    data = tool_msgs[-1]["content"] if tool_msgs else next(
        (m["content"] for m in msgs if m["role"] == "system" and "DATABASE RESULTS" in m["content"]), "")
    try:
        parsed = json.loads(data)
        summary = ", ".join(list(parsed)[:4])
    except (json.JSONDecodeError, TypeError):
        summary = data[:120]
    return {"model": body.get("model"), "done": True,
            "message": {"role": "assistant", "content": f"MOCK ANSWER based on database fields: {summary}"}}
