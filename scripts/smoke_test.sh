#!/usr/bin/env bash
# Smoke test for the Protected LLM. Run from the project root after `docker compose up -d`.
#   bash scripts/smoke_test.sh              all checks (LLM calls can take 10 to 90 s on CPU)
#   SKIP_LLM=1 bash scripts/smoke_test.sh   skip the LLM calls
set -u
cd "$(dirname "$0")/.."
KEY=$(grep -E '^SERVICE_KEY=' .env 2>/dev/null | cut -d= -f2-); KEY=${KEY:-dev-service-key}
API=${API:-localhost:8010}; UI=${UI:-localhost:${UI_PORT:-8080}}
H="X-Service-Key: $KEY"; PASS=0; FAIL=0
ok()  { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL  $1"; echo "        $2" | head -c 400; echo; FAIL=$((FAIL+1)); }
check() { local n=$1 w=$2; shift 2; local o; o=$("$@" 2>&1); if grep -q -- "$w" <<<"$o"; then ok "$n"; else bad "$n" "$o"; fi; }
post() { curl -s -m "${T:-20}" -H "$H" -H 'Content-Type: application/json' -X POST "$1" -d "$2"; }

echo "== Services"
check "ollama has the model" '"models"' curl -s -m 5 localhost:11434/api/tags
check "llm-api health"       '"database":"ok"' curl -s -m 5 $API/health
check "llm-api sees model"   '"model_pulled":true' curl -s -m 5 $API/health

echo "== Database through the read-only role"
check "patient summary"      '"found":true' post $API/v1/tools/get_patient_summary '{"patient_id":"P0012"}'
check "statistics"           'diagnosis_counts' post $API/v1/tools/get_statistics '{"kind":"diagnosis_counts"}'
check "doctor list"          '"doctor_id"' post $API/v1/tools/list_doctors '{}'
check "bad id rejected"      'patient_id must look like' post $API/v1/tools/get_diagnoses '{"patient_id":"1 OR 1=1"}'
check "no name/NIC in data"  '"found":true' post $API/v1/tools/get_patient_summary '{"patient_id":"P0001"}'
out=$(post $API/v1/tools/get_patient_summary '{"patient_id":"P0001"}')
if grep -qiE '"(full_name|nic|phone|email|mrn|dob)"' <<<"$out"; then bad "identifiers hidden" "$out"; else ok "identifiers hidden"; fi

echo "== Security"
check "key required"         'invalid' curl -s -m 5 -X POST $API/v1/chat -H 'Content-Type: application/json' -d '{"message":"x"}'
check "UI page"              'Hospital Assistant' curl -s -m 5 $UI/
check "UI proxy adds key"    '"tools"' curl -s -m 5 $UI/api/v1/tools

if [ "${SKIP_LLM:-0}" != "1" ]; then
  echo "== LLM (slow on CPU)"
  T=300 check "chat: summarise P0012" '"answer"' post $API/v1/chat '{"message":"Summarise patient P0012"}'
  T=300 check "chat via UI proxy"     '"answer"' curl -s -m 300 -X POST $UI/api/v1/chat -H 'Content-Type: application/json' -d '{"message":"List cardiology doctors"}'
fi
echo; echo "Result: $PASS passed, $FAIL failed"; [ "$FAIL" -eq 0 ]
