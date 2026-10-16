-- MediGuard AI: synthetic hospital database (PostgreSQL)
-- ALL DATA IS SYNTHETIC. No real patient information.
--
-- Base tables hold direct identifiers (name, NIC, phone, email, MRN, DOB).
-- The LLM never reads base tables. It reads the v_* views below through the
-- read-only role created in 03_readonly_role.sh (data minimisation).

CREATE TABLE doctors (
    doctor_id     VARCHAR(10) PRIMARY KEY,          -- e.g. D001
    full_name     VARCHAR(120) NOT NULL,
    specialty     VARCHAR(80)  NOT NULL,
    department    VARCHAR(80)  NOT NULL,
    email         VARCHAR(120) NOT NULL,
    phone         VARCHAR(20)  NOT NULL
);

CREATE TABLE patients (
    patient_id    VARCHAR(10) PRIMARY KEY,          -- pseudonymous internal id, e.g. P0001
    mrn           VARCHAR(12) UNIQUE NOT NULL,      -- medical record number (direct identifier)
    full_name     VARCHAR(120) NOT NULL,
    nic           VARCHAR(12)  UNIQUE NOT NULL,
    date_of_birth DATE         NOT NULL,
    sex           CHAR(1)      NOT NULL CHECK (sex IN ('M','F')),
    phone         VARCHAR(20)  NOT NULL,
    email         VARCHAR(120),
    district      VARCHAR(40)  NOT NULL,
    blood_group   VARCHAR(3)   NOT NULL,
    registered_on DATE         NOT NULL
);

CREATE TABLE appointments (
    appointment_id SERIAL PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    doctor_id      VARCHAR(10) NOT NULL REFERENCES doctors(doctor_id),
    scheduled_at   TIMESTAMP   NOT NULL,
    status         VARCHAR(12) NOT NULL CHECK (status IN ('scheduled','completed','cancelled','no_show')),
    reason         VARCHAR(200) NOT NULL
);

CREATE TABLE diagnoses (
    diagnosis_id   SERIAL PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    doctor_id      VARCHAR(10) NOT NULL REFERENCES doctors(doctor_id),
    icd10_code     VARCHAR(10) NOT NULL,
    description    VARCHAR(200) NOT NULL,
    diagnosed_on   DATE        NOT NULL,
    status         VARCHAR(12) NOT NULL CHECK (status IN ('active','resolved','chronic'))
);

CREATE TABLE clinical_notes (
    note_id        SERIAL PRIMARY KEY,
    patient_id     VARCHAR(10) NOT NULL REFERENCES patients(patient_id),
    doctor_id      VARCHAR(10) NOT NULL REFERENCES doctors(doctor_id),
    note_date      DATE        NOT NULL,
    note_type      VARCHAR(30) NOT NULL,
    note_text      TEXT        NOT NULL               -- written without patient names or identifiers
);

CREATE INDEX idx_appt_patient  ON appointments(patient_id);
CREATE INDEX idx_appt_doctor   ON appointments(doctor_id);
CREATE INDEX idx_appt_time     ON appointments(scheduled_at);
CREATE INDEX idx_diag_patient  ON diagnoses(patient_id);
CREATE INDEX idx_diag_code     ON diagnoses(icd10_code);
CREATE INDEX idx_notes_patient ON clinical_notes(patient_id);

-- ---------------------------------------------------------------------------
-- Views the LLM is allowed to read. No name, NIC, phone, email, MRN or DOB.
-- Age is computed, so the exact date of birth never leaves the database.
-- ---------------------------------------------------------------------------
CREATE VIEW v_patients AS
SELECT patient_id,
       DATE_PART('year', AGE(CURRENT_DATE, date_of_birth))::INT AS age,
       sex,
       blood_group,
       registered_on
FROM patients;

CREATE VIEW v_doctors AS
SELECT doctor_id, full_name, specialty, department
FROM doctors;

CREATE VIEW v_appointments AS
SELECT a.appointment_id, a.patient_id, a.doctor_id, d.specialty AS doctor_specialty,
       a.scheduled_at, a.status, a.reason
FROM appointments a JOIN doctors d ON d.doctor_id = a.doctor_id;

CREATE VIEW v_diagnoses AS
SELECT diagnosis_id, patient_id, doctor_id, icd10_code, description, diagnosed_on, status
FROM diagnoses;

CREATE VIEW v_clinical_notes AS
SELECT note_id, patient_id, doctor_id, note_date, note_type, note_text
FROM clinical_notes;
