-- Схема базы данных CRM аренды помещений (SQLite)
-- Деньги хранятся в копейках (INTEGER), даты - ISO-строками, расчётный месяц - 'ГГГГ-ММ'.

CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT    NOT NULL UNIQUE,
    full_name            TEXT    NOT NULL,
    password_hash        TEXT    NOT NULL,
    role                 TEXT    NOT NULL CHECK (role IN ('admin', 'manager')),
    is_active            INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0, 1)),
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    created_at           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    contact_person TEXT,
    phone          TEXT,
    email          TEXT,
    inn_encrypted  TEXT NOT NULL,          -- ИНН в зашифрованном виде (Fernet)
    inn_hash       TEXT NOT NULL UNIQUE,   -- HMAC-индекс для проверки уникальности
    note           TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS premises (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT    NOT NULL UNIQUE,
    floor  INTEGER NOT NULL,
    area   REAL    NOT NULL CHECK (area > 0),
    status TEXT    NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'rented', 'repair')),
    note   TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       TEXT    NOT NULL UNIQUE,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id)  ON DELETE RESTRICT,
    premises_id  INTEGER NOT NULL REFERENCES premises(id) ON DELETE RESTRICT,
    start_date   TEXT    NOT NULL,
    end_date     TEXT    NOT NULL,
    monthly_rent INTEGER NOT NULL CHECK (monthly_rent > 0),
    is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at   TEXT    NOT NULL,
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS rent_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    new_rent    INTEGER NOT NULL CHECK (new_rent > 0),
    valid_from  TEXT    NOT NULL,          -- 'ГГГГ-ММ': с какого месяца действует ставка
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE (contract_id, valid_from)
);

CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE RESTRICT,
    period      TEXT    NOT NULL,          -- 'ГГГГ-ММ': за какой месяц оплата
    amount      INTEGER NOT NULL CHECK (amount > 0),
    paid_at     TEXT    NOT NULL,
    note        TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username    TEXT,
    action      TEXT NOT NULL,
    object_type TEXT,
    object_id   INTEGER,
    details     TEXT,
    ip          TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contracts_tenant   ON contracts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contracts_premises ON contracts(premises_id);
CREATE INDEX IF NOT EXISTS idx_payments_contract  ON payments(contract_id, period);
CREATE INDEX IF NOT EXISTS idx_audit_created      ON audit_log(created_at);
