# Protected LLM (J26-CS-321): Ollama + synthetic hospital DB + API + chat UI

One Docker Compose stack, everything local, synthetic data only, no external LLM APIs.

```
Browser --> chat-ui (nginx :8080) --> llm-api (:8010) --> Ollama (:11434)  local model
                                          |
                                          +--> hospital-db (Postgres :5432)  read-only role, views only
```

| Service | What it is |
|---|---|
| `ollama` + `ollama-init` | Local LLM server. `ollama-init` downloads the model once, then exits |
| `hospital-db` | PostgreSQL 16 with synthetic data: 24 doctors, 200 patients, 825 appointments, 341 diagnoses, 676 clinical notes |
| `llm-api` | FastAPI. Gives the model 7 read-only database tools. **This is the API your teammates integrate with** |
| `chat-ui` | Basic chat page for doctors and staff. nginx adds the service key, so the browser never sees it |

Files: `docker-compose.yml`, `.env.example`, `hospital/db/` (schema, seed, read-only role, data generator), `hospital/llm-api/`, `ui/`, `scripts/`, `docs/API.md`.

## Deploy (Ubuntu VM with Docker)

```bash
unzip protected-llm.zip && cd protected-llm

# 1. Check the VM and get a model recommendation
bash scripts/check_vm.sh

# 2. Configure: set OLLAMA_MODEL (as recommended) and the 3 secrets
cp .env.example .env
nano .env

# 3. Start everything (first run downloads the model: 1 to 5 GB, several minutes)
docker compose up -d --build

# 4. Watch it come up. Wait until llm-api shows "healthy" (ollama-init shows "Exited (0)", that is normal)
docker compose ps
docker compose logs -f ollama-init        # model download progress, Ctrl+C to leave

# 5. Test
bash scripts/smoke_test.sh                # 14 checks; SKIP_LLM=1 to skip the slow LLM calls
```

Open `http://<vm-ip>:8080` and click an example, or type `Summarise patient P0012`.

If you cannot open port 8080 from your laptop: `sudo ufw allow 8080/tcp`, or use an SSH tunnel: `ssh -L 8080:localhost:8080 user@<vm-ip>`.

### Choosing the model

| Free RAM | `OLLAMA_MODEL` | Download |
|---|---|---|
| under 5 GB | `qwen2.5:1.5b` | 986 MB |
| 5 to 11 GB | `qwen2.5:3b` (default) | 1.9 GB |
| 11 GB or more | `qwen2.5:7b` | 4.7 GB |

With fewer than 4 CPU cores use `qwen2.5:1.5b`, or answers will be slow. To switch later: edit `OLLAMA_MODEL` in `.env`, then `docker compose up -d`. NVIDIA GPU: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d` (needs the NVIDIA Container Toolkit).

## For teammates (API)

See **`docs/API.md`**. In short:

```bash
KEY=<SERVICE_KEY from .env>
curl -s localhost:8010/health
curl -s -X POST localhost:8010/v1/chat -H "X-Service-Key: $KEY" -H 'Content-Type: application/json' \
     -d '{"message":"Summarise patient P0012"}'
```

Interactive docs (Swagger): `http://<vm-ip>:8010/docs`. By default port 8010 only accepts connections from the VM itself. To let teammates call it from their own machines, either use an SSH tunnel (`ssh -L 8010:localhost:8010 user@<vm-ip>`, safest), or set `LLM_API_BIND=0.0.0.0` in `.env`, run `docker compose up -d`, and allow the port in your firewall. The service key is the only protection, so share it privately and keep real data out of this system.

## How the LLM uses the database

1. The model never writes SQL. It picks one of 7 fixed tools (for example `get_diagnoses` with `patient_id=P0012`), and the API runs a parameterised query.
2. The API connects as `llm_reader`, a read-only role that can `SELECT` only from `v_*` views. Those views have no names, NIC, phone, email, MRN or date of birth, only age and patient id.
3. If the model does not support tools, `LLM_MODE=auto` falls back to context mode: the API looks up the data first and puts it in the prompt.

Patients are therefore asked about by **id** (P0001 to P0200), not by name. Ids are internal pseudonyms, not personal data.

## Everyday commands

```bash
docker compose ps                          # status
docker compose logs -f llm-api             # logs (also: ollama, hospital-db, chat-ui)
docker compose restart llm-api             # restart one service
docker compose down                        # stop (keeps data and model)
docker compose down -v                     # stop and delete database + model (full reset)
docker compose exec hospital-db psql -U hospital_admin hospital     # open the database
python3 hospital/db/generate_synthetic_data.py --patients 500 --seed 7 --out hospital/db/init/02_seed.sql   # bigger dataset, then reset with down -v
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied` on Docker | `sudo usermod -aG docker $USER`, log out and in |
| `set SERVICE_KEY in .env` | You skipped `cp .env.example .env` |
| `llm-api` waits a long time | The model is still downloading: `docker compose logs -f ollama-init` |
| Answers take over a minute | Use a smaller model, or check `nproc` (4+ cores recommended) |
| UI shows "model still downloading" | Wait, then refresh |
| Changed passwords in `.env` after first start | The database keeps the old ones: `docker compose down -v` and start again |
| Out of memory, containers killed | Use `qwen2.5:1.5b`; check `free -h` |
| Answer says data is missing | Use patient ids like `P0012`; names are not in the database the AI can see |

## Limits of this build

- No user login. Anyone who can open the UI can chat. Add authentication before more than a few people use it.
- No HTTPS. Put a reverse proxy in front for anything beyond a lab network.
- Small local models make mistakes. Answers are information support only, and every answer should be checked against the record.
- Chat history lives in the browser tab only; the API stores nothing.
