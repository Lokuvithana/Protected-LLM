"""Read-only database tools the LLM can call.

Every query:
  * runs as the `llm_reader` role (SELECT on v_* views only, read-only transactions),
  * uses bound parameters (no SQL is ever written by the LLM),
  * validates ids and caps row counts.
The views contain no names, NIC, phone, email, MRN or date of birth.
"""
import datetime as dt
import os
import re

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://llm_reader:change-me@hospital-db:5432/hospital")

PATIENT_ID = re.compile(r"^P\d{4}$")
DOCTOR_ID = re.compile(r"^D\d{3}$")


class ToolError(ValueError):
    pass


def _query(sql, params=()):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _pid(value):
    value = str(value or "").strip().upper()
    if not PATIENT_ID.match(value):
        raise ToolError("patient_id must look like P0001")
    return value


def _did(value):
    value = str(value or "").strip().upper()
    if not DOCTOR_ID.match(value):
        raise ToolError("doctor_id must look like D001")
    return value


def _limit(value, default, maximum):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _date(value):
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ToolError("dates must be YYYY-MM-DD") from exc


# ----------------------------------------------------------------------------- tools
def get_patient_summary(patient_id):
    pid = _pid(patient_id)
    patient = _query("SELECT * FROM v_patients WHERE patient_id = %s", (pid,))
    if not patient:
        return {"found": False, "patient_id": pid}
    return {
        "found": True,
        "patient": patient[0],
        "diagnoses": _query("SELECT icd10_code, description, diagnosed_on, status FROM v_diagnoses "
                            "WHERE patient_id = %s ORDER BY diagnosed_on DESC", (pid,)),
        "upcoming_appointments": _query("SELECT scheduled_at, doctor_id, doctor_specialty, status, reason FROM v_appointments "
                                        "WHERE patient_id = %s AND scheduled_at >= NOW() ORDER BY scheduled_at LIMIT 5", (pid,)),
        "recent_notes": _query("SELECT note_date, note_type, note_text FROM v_clinical_notes "
                               "WHERE patient_id = %s ORDER BY note_date DESC LIMIT 3", (pid,)),
    }


def search_patients(diagnosis_keyword=None, icd10_code=None, sex=None, min_age=None, max_age=None, limit=10):
    sql = ["SELECT DISTINCT p.patient_id, p.age, p.sex, p.blood_group FROM v_patients p "
           "LEFT JOIN v_diagnoses d ON d.patient_id = p.patient_id WHERE 1=1"]
    params = []
    if diagnosis_keyword:
        sql.append("AND d.description ILIKE %s")
        params.append(f"%{str(diagnosis_keyword)[:60]}%")
    if icd10_code:
        sql.append("AND d.icd10_code ILIKE %s")
        params.append(f"{str(icd10_code)[:10]}%")
    if sex:
        s = str(sex).strip().upper()[:1]
        if s not in ("M", "F"):
            raise ToolError("sex must be M or F")
        sql.append("AND p.sex = %s")
        params.append(s)
    if min_age is not None:
        sql.append("AND p.age >= %s")
        params.append(_limit(min_age, 0, 120))
    if max_age is not None:
        sql.append("AND p.age <= %s")
        params.append(_limit(max_age, 120, 120))
    sql.append("ORDER BY p.patient_id LIMIT %s")
    params.append(_limit(limit, 10, 50))
    rows = _query(" ".join(sql), params)
    return {"count": len(rows), "patients": rows}


def get_appointments(patient_id=None, doctor_id=None, status=None, date_from=None, date_to=None, limit=20):
    sql = ["SELECT appointment_id, patient_id, doctor_id, doctor_specialty, scheduled_at, status, reason "
           "FROM v_appointments WHERE 1=1"]
    params = []
    if patient_id:
        sql.append("AND patient_id = %s")
        params.append(_pid(patient_id))
    if doctor_id:
        sql.append("AND doctor_id = %s")
        params.append(_did(doctor_id))
    if status:
        st = str(status).lower()
        if st not in ("scheduled", "completed", "cancelled", "no_show"):
            raise ToolError("status must be scheduled, completed, cancelled or no_show")
        sql.append("AND status = %s")
        params.append(st)
    if _date(date_from):
        sql.append("AND scheduled_at >= %s")
        params.append(_date(date_from))
    if _date(date_to):
        sql.append("AND scheduled_at < %s::date + 1")
        params.append(_date(date_to))
    sql.append("ORDER BY scheduled_at LIMIT %s")
    params.append(_limit(limit, 20, 50))
    rows = _query(" ".join(sql), params)
    return {"count": len(rows), "appointments": rows}


def get_diagnoses(patient_id):
    pid = _pid(patient_id)
    rows = _query("SELECT icd10_code, description, diagnosed_on, status, doctor_id FROM v_diagnoses "
                  "WHERE patient_id = %s ORDER BY diagnosed_on DESC", (pid,))
    return {"patient_id": pid, "count": len(rows), "diagnoses": rows}


def get_clinical_notes(patient_id, limit=5):
    pid = _pid(patient_id)
    rows = _query("SELECT note_date, note_type, doctor_id, note_text FROM v_clinical_notes "
                  "WHERE patient_id = %s ORDER BY note_date DESC LIMIT %s", (pid, _limit(limit, 5, 20)))
    return {"patient_id": pid, "count": len(rows), "notes": rows}


def list_doctors(specialty=None):
    if specialty:
        rows = _query("SELECT * FROM v_doctors WHERE specialty ILIKE %s ORDER BY doctor_id",
                      (f"%{str(specialty)[:60]}%",))
    else:
        rows = _query("SELECT * FROM v_doctors ORDER BY doctor_id")
    return {"count": len(rows), "doctors": rows}


def get_statistics(kind="diagnosis_counts"):
    queries = {
        "diagnosis_counts": "SELECT icd10_code, description, COUNT(DISTINCT patient_id) AS patients "
                            "FROM v_diagnoses GROUP BY icd10_code, description ORDER BY patients DESC",
        "appointment_status_counts": "SELECT status, COUNT(*) AS appointments FROM v_appointments GROUP BY status ORDER BY 2 DESC",
        "patients_by_sex": "SELECT sex, COUNT(*) AS patients, ROUND(AVG(age)) AS average_age FROM v_patients GROUP BY sex",
        "appointments_by_specialty": "SELECT doctor_specialty, COUNT(*) AS appointments FROM v_appointments "
                                     "GROUP BY doctor_specialty ORDER BY 2 DESC",
    }
    if kind not in queries:
        raise ToolError(f"kind must be one of {sorted(queries)}")
    return {"kind": kind, "rows": _query(queries[kind])}


TOOL_FUNCTIONS = {
    "get_patient_summary": get_patient_summary,
    "search_patients": search_patients,
    "get_appointments": get_appointments,
    "get_diagnoses": get_diagnoses,
    "get_clinical_notes": get_clinical_notes,
    "list_doctors": list_doctors,
    "get_statistics": get_statistics,
}


def _fn(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


PID = {"type": "string", "description": "Patient id, for example P0012"}
TOOL_SCHEMAS = [
    _fn("get_patient_summary", "Age, sex, blood group, diagnoses, upcoming appointments and recent notes for one patient.",
        {"patient_id": PID}, ["patient_id"]),
    _fn("search_patients", "Find patients by diagnosis, ICD-10 code, sex or age range.",
        {"diagnosis_keyword": {"type": "string", "description": "Word in the diagnosis, e.g. diabetes"},
         "icd10_code": {"type": "string", "description": "ICD-10 code or prefix, e.g. E11"},
         "sex": {"type": "string", "enum": ["M", "F"]},
         "min_age": {"type": "integer"}, "max_age": {"type": "integer"},
         "limit": {"type": "integer", "description": "Max rows, default 10"}}),
    _fn("get_appointments", "List appointments, filtered by patient, doctor, status or date range (YYYY-MM-DD).",
        {"patient_id": PID, "doctor_id": {"type": "string", "description": "Doctor id, e.g. D003"},
         "status": {"type": "string", "enum": ["scheduled", "completed", "cancelled", "no_show"]},
         "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}),
    _fn("get_diagnoses", "All diagnoses for one patient.", {"patient_id": PID}, ["patient_id"]),
    _fn("get_clinical_notes", "Most recent clinical notes for one patient.",
        {"patient_id": PID, "limit": {"type": "integer"}}, ["patient_id"]),
    _fn("list_doctors", "List doctors, optionally by specialty.", {"specialty": {"type": "string"}}),
    _fn("get_statistics", "Hospital-wide counts.",
        {"kind": {"type": "string", "enum": ["diagnosis_counts", "appointment_status_counts",
                                             "patients_by_sex", "appointments_by_specialty"]}}, ["kind"]),
]


def run_tool(name, arguments):
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        raise ToolError(f"unknown tool {name}")
    args = {k: v for k, v in (arguments or {}).items() if v not in (None, "")}
    try:
        return fn(**args)
    except TypeError as exc:
        raise ToolError(f"bad arguments for {name}: {exc}") from exc
