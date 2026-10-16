# LLM API reference (for teammates)

Base URL: `http://<vm-ip>:8010` (or `http://localhost:8010` through an SSH tunnel).
Swagger UI: `/docs`. OpenAPI JSON: `/openapi.json` (generate a client from it if you like).

**Auth:** every `/v1/*` call needs the header `X-Service-Key: <SERVICE_KEY from .env>`. `/health` is open. A wrong or missing key returns `401`.

```bash
KEY=<your key>; H="X-Service-Key: $KEY"; J='Content-Type: application/json'
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Is the database up, is Ollama up, is the model downloaded |
| POST | `/v1/chat` | Ask the protected LLM a question. It queries the database and answers |
| GET | `/v1/tools` | The 7 database tools the model can call (JSON schemas) |
| POST | `/v1/tools/{name}` | Run one tool directly, with no LLM. Fast, deterministic: use it to test the database |

### GET /health

```bash
curl -s localhost:8010/health
```
```json
{"service":"hospital-llm-api","model":"qwen2.5:3b","mode":"auto","database":"ok","ollama":"ok","model_pulled":true,"status":"ok"}
```
`status` is `ok` when the database works and the model is downloaded, otherwise `degraded`.

### POST /v1/chat

Request:

| Field | Type | Notes |
|---|---|---|
| `message` | string, required | 1 to 8000 characters |
| `history` | array of `{role, content}` | Optional. `role` is `user` or `assistant`. The last 6 turns are used. The API is stateless, so send the history yourself |
| `request_id` | string | Optional. Echoed back so you can correlate logs |

```bash
curl -s -X POST localhost:8010/v1/chat -H "$H" -H "$J" -d '{
  "message": "What are the diagnoses of P0005?",
  "history": [],
  "request_id": "my-trace-001"
}'
```

Response `200`:

```json
{
  "request_id": "my-trace-001",
  "answer": "P0005 has: ...",
  "mode": "tools",
  "model": "qwen2.5:3b",
  "tool_calls": [{"name": "get_diagnoses", "arguments": {"patient_id": "P0005"}, "error": null}],
  "latency_ms": 18400
}
```

- `mode` is `tools` (the model chose database tools) or `context` (the API fetched data first; used when the model has no tool support).
- `tool_calls` lists every database call made. Use it for audit logs.
- **Latency:** CPU models take about 5 to 90 s. Set your HTTP client timeout to 300 s.

Errors: `401` bad key, `422` bad body, `503` Ollama unreachable, `400` `LLM_MODE=tools` with a model that has no tool support.

### GET /v1/tools and POST /v1/tools/{name}

| Tool | Arguments (all strings or integers) |
|---|---|
| `get_patient_summary` | `patient_id` |
| `search_patients` | `diagnosis_keyword`, `icd10_code`, `sex`, `min_age`, `max_age`, `limit` |
| `get_appointments` | `patient_id`, `doctor_id`, `status`, `date_from`, `date_to`, `limit` |
| `get_diagnoses` | `patient_id` |
| `get_clinical_notes` | `patient_id`, `limit` |
| `list_doctors` | `specialty` |
| `get_statistics` | `kind`: `diagnosis_counts`, `appointment_status_counts`, `patients_by_sex` or `appointments_by_specialty` |

Ids: patients `P0001` to `P0200`, doctors `D001` to `D024`. Anything else returns `422` (this also blocks SQL injection).

```bash
curl -s -X POST localhost:8010/v1/tools/search_patients -H "$H" -H "$J" -d '{"diagnosis_keyword":"dengue","limit":5}'
curl -s -X POST localhost:8010/v1/tools/get_diagnoses  -H "$H" -H "$J" -d '{"patient_id":"bad"}'
# {"detail":"patient_id must look like P0001"}
```

Response shape: `{"tool": "<name>", "result": {...}}`.

## What the data contains

The LLM and these endpoints only see the `v_*` views: patient id, age, sex, blood group; diagnoses (ICD-10); appointments; clinical notes; doctor id, specialty and department. They **never** see names, NIC, phone, email, MRN or date of birth. Those exist only in the base tables, which the API's database role cannot read.

## Python example

```python
import httpx

API, KEY = "http://localhost:8010", "your-service-key"

def ask(message, history=None):
    r = httpx.post(f"{API}/v1/chat",
                   headers={"X-Service-Key": KEY},
                   json={"message": message, "history": history or []},
                   timeout=300)
    r.raise_for_status()
    return r.json()

out = ask("Summarise patient P0012")
print(out["answer"], out["tool_calls"], out["latency_ms"])
```

## Testing your own component without a model

If your laptop is too small for a model, or you only want to test your plumbing, run the fake Ollama and point the API at it. Answers are canned, so never judge quality with it:

```bash
pip install fastapi uvicorn
uvicorn scripts.mock_ollama:app --port 11434      # from the project root
```

## Where to add things

| Want to | Edit |
|---|---|
| Add or change a database tool | `hospital/llm-api/app/tools.py` (schema + SQL + registry) |
| Change the model's instructions | `SYSTEM_PROMPT` in `hospital/llm-api/app/main.py` |
| Add or change data or tables | `hospital/db/init/01_schema.sql`, then regenerate the seed with `hospital/db/generate_synthetic_data.py`, then `docker compose down -v && docker compose up -d --build` |
| Change the UI | `ui/index.html` (then `docker compose up -d --build chat-ui`) |

After editing the API: `docker compose up -d --build llm-api`.
