"""Generate SYNTHETIC hospital data as SQL inserts (02_seed.sql).

Standard library only. Deterministic (fixed seed), so every teammate gets
exactly the same database. Every name, NIC, phone number and note is invented.

Usage:
    python3 hospital/db/generate_synthetic_data.py              # writes hospital/db/init/02_seed.sql
    python3 hospital/db/generate_synthetic_data.py --patients 500 --seed 7
"""
import argparse
import datetime as dt
import os
import random

FIRST_M = ["Nimal", "Kamal", "Sunil", "Ruwan", "Chamara", "Dinesh", "Kasun", "Tharindu", "Lahiru",
           "Pradeep", "Asanka", "Mahesh", "Sanjaya", "Nuwan", "Isuru", "Dulan", "Sahan", "Malith",
           "Arjun", "Kumar", "Rizwan", "Fazil", "Suresh", "Gayan", "Janaka", "Roshan", "Thilina"]
FIRST_F = ["Nadeesha", "Dilini", "Sachini", "Chathurika", "Ishara", "Hiruni", "Kavindi", "Nethmi",
           "Tharushi", "Anjali", "Priyanka", "Shalini", "Fathima", "Ayesha", "Sewwandi", "Madushani",
           "Rashmi", "Dulani", "Hasini", "Nirosha", "Lakmini", "Kumari", "Meena", "Gayani"]
LAST = ["Perera", "Fernando", "Silva", "Jayasinghe", "Bandara", "Wijeratne", "Gunawardena",
        "Rathnayake", "Dissanayake", "Herath", "Senanayake", "Wickramasinghe", "Karunaratne",
        "Abeysekara", "Jayawardena", "Ranasinghe", "Samarasinghe", "Kumarasinghe", "Liyanage",
        "Ekanayake", "Weerasinghe", "Mendis", "Rajapaksha", "Pathirana", "Navaratnam", "Sivakumar",
        "Mohamed", "Hameed"]
DISTRICTS = ["Colombo", "Gampaha", "Kalutara", "Kandy", "Matale", "Kurunegala", "Galle", "Matara",
             "Ratnapura", "Kegalle", "Badulla", "Anuradhapura", "Jaffna", "Batticaloa", "Trincomalee"]
BLOOD = ["O+", "O+", "O+", "A+", "A+", "B+", "B+", "AB+", "O-", "A-", "B-", "AB-"]

SPECIALTIES = [
    ("General Medicine", "Medical Unit"), ("Cardiology", "Cardiology Unit"),
    ("Endocrinology", "Diabetes Centre"), ("Respiratory Medicine", "Chest Clinic"),
    ("Nephrology", "Renal Unit"), ("Neurology", "Neurology Unit"), ("Paediatrics", "Children's Ward"),
    ("Obstetrics and Gynaecology", "Maternity Unit"), ("Psychiatry", "Mental Health Unit"),
    ("Oncology", "Cancer Unit"), ("Infectious Diseases", "Infectious Diseases Unit"),
    ("General Surgery", "Surgical Unit"),
]

# (ICD-10, description, specialty, weight, typical status)
CONDITIONS = [
    ("E11.9", "Type 2 diabetes mellitus without complications", "Endocrinology", 18, "chronic"),
    ("I10", "Essential (primary) hypertension", "Cardiology", 18, "chronic"),
    ("E78.5", "Hyperlipidaemia, unspecified", "General Medicine", 8, "chronic"),
    ("J45.9", "Asthma, unspecified", "Respiratory Medicine", 7, "chronic"),
    ("I25.10", "Chronic ischaemic heart disease", "Cardiology", 5, "chronic"),
    ("N18.3", "Chronic kidney disease, stage 3", "Nephrology", 4, "chronic"),
    ("J18.9", "Pneumonia, unspecified organism", "Respiratory Medicine", 5, "resolved"),
    ("A90", "Dengue fever", "Infectious Diseases", 6, "resolved"),
    ("A01.0", "Typhoid fever", "Infectious Diseases", 2, "resolved"),
    ("K29.7", "Gastritis, unspecified", "General Medicine", 5, "resolved"),
    ("F32.9", "Depressive episode, unspecified", "Psychiatry", 4, "active"),
    ("G40.9", "Epilepsy, unspecified", "Neurology", 2, "chronic"),
    ("O24.4", "Gestational diabetes mellitus", "Obstetrics and Gynaecology", 2, "active"),
    ("J06.9", "Acute upper respiratory infection", "Paediatrics", 5, "resolved"),
    ("K35.8", "Acute appendicitis", "General Surgery", 2, "resolved"),
    ("A15.0", "Pulmonary tuberculosis", "Infectious Diseases", 1, "active"),
    ("B20", "HIV disease", "Infectious Diseases", 1, "chronic"),
    ("C91.0", "Acute lymphoblastic leukaemia", "Oncology", 1, "active"),
    ("C50.9", "Malignant neoplasm of breast", "Oncology", 1, "active"),
    ("G20", "Parkinson's disease", "Neurology", 1, "chronic"),
]

MEDS = {
    "E11.9": "metformin 500 mg twice daily", "I10": "amlodipine 5 mg daily",
    "E78.5": "atorvastatin 20 mg at night", "J45.9": "salbutamol inhaler as needed",
    "I25.10": "aspirin 75 mg daily and atorvastatin 40 mg", "N18.3": "losartan 50 mg daily",
    "J18.9": "amoxicillin-clavulanate for 7 days", "A90": "paracetamol and oral fluids",
    "A01.0": "azithromycin for 7 days", "K29.7": "omeprazole 20 mg daily",
    "F32.9": "sertraline 50 mg daily", "G40.9": "sodium valproate 500 mg twice daily",
    "O24.4": "dietary control with glucose monitoring", "J06.9": "symptomatic treatment",
    "K35.8": "post-operative antibiotics", "A15.0": "standard anti-TB regimen",
    "B20": "antiretroviral therapy", "C91.0": "induction chemotherapy as per protocol",
    "C50.9": "adjuvant therapy as per oncology plan", "G20": "levodopa-carbidopa",
}
REASONS = ["Follow-up review", "Medication review", "New complaint", "Lab results review",
           "Routine check-up", "Post-discharge review", "Chest pain evaluation", "Fever assessment",
           "Blood pressure check", "Glucose control review"]
NOTE_TYPES = ["Progress note", "Consultation note", "Discharge summary", "Clinic note"]
TODAY = dt.date(2026, 10, 15)


def q(value):
    """SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def make_nic(rng, dob, sex):
    day_of_year = dob.timetuple().tm_yday + (500 if sex == "F" else 0)
    if dob.year < 2000 and rng.random() < 0.5:
        return f"{dob.year % 100:02d}{day_of_year:03d}{rng.randint(0, 9999):04d}V"
    return f"{dob.year}{day_of_year:03d}{rng.randint(0, 99999):05d}"


def make_note(rng, cond, age, sex):
    code, desc = cond[0], cond[1]
    who = f"{age}-year-old {'male' if sex == 'M' else 'female'}"
    bp = f"{rng.randint(110, 165)}/{rng.randint(70, 100)}"
    templates = [
        f"{who} reviewed for {desc.lower()}. Patient reports {rng.choice(['good adherence', 'occasional missed doses', 'mild fatigue', 'no new symptoms'])}. "
        f"BP {bp} mmHg. Plan: continue {MEDS[code]}, review in {rng.choice([2, 4, 6, 12])} weeks.",
        f"Follow-up for {desc.lower()}. Examination unremarkable apart from {rng.choice(['mild pallor', 'bilateral wheeze', 'pedal oedema', 'no significant findings'])}. "
        f"Investigations ordered: {rng.choice(['FBC, FBS', 'HbA1c, lipid profile', 'serum creatinine', 'chest X-ray', 'ECG'])}. Current treatment: {MEDS[code]}.",
        f"{who} with {desc.lower()}. Symptoms {rng.choice(['improving', 'stable', 'worsening slightly'])}. "
        f"Counselled on diet, exercise and medication adherence. Continue {MEDS[code]}.",
    ]
    return rng.choice(templates)


def generate(n_patients=200, n_doctors=24, seed=42):
    rng = random.Random(seed)
    out = ["-- AUTO-GENERATED by generate_synthetic_data.py. SYNTHETIC DATA ONLY.", "BEGIN;"]

    # Doctors: two per specialty
    doctors = []
    for i in range(n_doctors):
        spec, dept = SPECIALTIES[i % len(SPECIALTIES)]
        sex = rng.choice("MF")
        name = f"Dr. {rng.choice(FIRST_M if sex == 'M' else FIRST_F)} {rng.choice(LAST)}"
        did = f"D{i + 1:03d}"
        doctors.append((did, spec))
        out.append("INSERT INTO doctors VALUES ({});".format(", ".join(map(q, [
            did, name, spec, dept, f"{did.lower()}@hospital.example", f"0112{rng.randint(100000, 999999)}"]))))
    by_spec = {}
    for did, spec in doctors:
        by_spec.setdefault(spec, []).append(did)

    weights = [c[3] for c in CONDITIONS]
    n_appt = n_diag = n_note = 0
    used_nic = set()
    for i in range(n_patients):
        pid = f"P{i + 1:04d}"
        sex = rng.choice("MF")
        age = min(95, max(1, int(rng.gauss(48, 20))))
        dob = TODAY - dt.timedelta(days=age * 365 + rng.randint(0, 364))
        nic = make_nic(rng, dob, sex)
        while nic in used_nic:
            nic = make_nic(rng, dob, sex)
        used_nic.add(nic)
        first = rng.choice(FIRST_M if sex == "M" else FIRST_F)
        last = rng.choice(LAST)
        out.append("INSERT INTO patients VALUES ({});".format(", ".join(map(q, [
            pid, f"{10000000 + i * 37:08d}", f"{first} {last}", nic, dob.isoformat(), sex,
            f"07{rng.choice('0125678')}{rng.randint(1000000, 9999999)}",
            f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@mail.example",
            rng.choice(DISTRICTS), rng.choice(BLOOD),
            (TODAY - dt.timedelta(days=rng.randint(30, 2500))).isoformat()]))))

        # 1 to 3 conditions per patient
        conds = []
        for _ in range(rng.choice([1, 1, 2, 2, 3])):
            c = rng.choices(CONDITIONS, weights=weights)[0]
            if c not in conds:
                conds.append(c)
        for c in conds:
            did = rng.choice(by_spec.get(c[2], [d for d, _ in doctors]))
            diag_date = TODAY - dt.timedelta(days=rng.randint(10, 1500))
            out.append("INSERT INTO diagnoses (patient_id, doctor_id, icd10_code, description, diagnosed_on, status) "
                       "VALUES ({});".format(", ".join(map(q, [pid, did, c[0], c[1], diag_date.isoformat(), c[4]]))))
            n_diag += 1
            # 1 to 3 notes per condition
            for _ in range(rng.randint(1, 3)):
                nd = diag_date + dt.timedelta(days=rng.randint(0, max(1, (TODAY - diag_date).days)))
                out.append("INSERT INTO clinical_notes (patient_id, doctor_id, note_date, note_type, note_text) "
                           "VALUES ({});".format(", ".join(map(q, [pid, did, nd.isoformat(), rng.choice(NOTE_TYPES),
                                                                    make_note(rng, c, age, sex)]))))
                n_note += 1

        # 2 to 6 appointments, past and future
        for _ in range(rng.randint(2, 6)):
            c = rng.choice(conds)
            did = rng.choice(by_spec.get(c[2], [d for d, _ in doctors]))
            offset = rng.randint(-240, 60)
            when = dt.datetime.combine(TODAY + dt.timedelta(days=offset),
                                       dt.time(rng.choice([8, 9, 10, 11, 13, 14, 15]), rng.choice([0, 15, 30, 45])))
            if offset > 0:
                status = "scheduled"
            else:
                status = rng.choices(["completed", "cancelled", "no_show"], weights=[85, 8, 7])[0]
            out.append("INSERT INTO appointments (patient_id, doctor_id, scheduled_at, status, reason) "
                       "VALUES ({});".format(", ".join(map(q, [pid, did, when.isoformat(sep=" "), status,
                                                                f"{rng.choice(REASONS)}: {c[1]}"]))))
            n_appt += 1

    out.append("COMMIT;")
    summary = dict(doctors=n_doctors, patients=n_patients, diagnoses=n_diag, clinical_notes=n_note, appointments=n_appt)
    out.insert(1, "-- " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return "\n".join(out) + "\n", summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=200)
    ap.add_argument("--doctors", type=int, default=24)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "init", "02_seed.sql"))
    a = ap.parse_args()
    sql, summary = generate(a.patients, a.doctors, a.seed)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"Wrote {a.out}: {summary}")
