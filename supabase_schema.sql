-- XpenzIQ PostgreSQL schema
-- Generated from the current Alembic schema (head: 0010_reimbursement_categories).
-- DESTRUCTIVE RESET: running this script deletes all existing XpenzIQ app data.
-- Unrelated tables and objects in Supabase are not dropped.

BEGIN;

DROP TABLE IF EXISTS user_claims CASCADE;
DROP TABLE IF EXISTS reimbursement_categories CASCADE;
DROP TABLE IF EXISTS reimbursement_claims CASCADE;
DROP TABLE IF EXISTS reimbursement_memberships CASCADE;
DROP TABLE IF EXISTS reimbursement_teams CASCADE;
DROP TABLE IF EXISTS invoice_items CASCADE;
DROP TABLE IF EXISTS invoices CASCADE;
DROP TABLE IF EXISTS income CASCADE;
DROP TABLE IF EXISTS budgets CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS alembic_version CASCADE;
DROP SEQUENCE IF EXISTS employee_id_seq CASCADE;

CREATE SEQUENCE employee_id_seq START WITH 1;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE users (
    id UUID NOT NULL,
    email VARCHAR(320) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    employee_id VARCHAR(16),
    user_role VARCHAR(12) NOT NULL DEFAULT 'user',
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    preferred_currency VARCHAR(3) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_users_employee_id UNIQUE (employee_id),
    CONSTRAINT ck_users_role CHECK (user_role IN ('admin', 'user'))
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_employee_id ON users (employee_id);
CREATE INDEX ix_users_role ON users (user_role);

-- The documents table also stores queued work; a separate Redis queue table is not used.
CREATE TABLE documents (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(80) NOT NULL,
    file_size INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    stage VARCHAR(80) NOT NULL,
    error_code VARCHAR(60),
    error_message VARCHAR(512),
    extraction JSONB,
    temp_path TEXT,
    file_sha256 VARCHAR(64),
    allow_duplicate_invoice BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_documents_user_file_sha256 UNIQUE (user_id, file_sha256),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_documents_user_id ON documents (user_id);
CREATE INDEX ix_documents_user_status_created
    ON documents (user_id, status, created_at);

CREATE TABLE income (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    income_date DATE NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    description TEXT,
    currency VARCHAR(3) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_income_user_date ON income (user_id, income_date);
CREATE INDEX ix_income_user_id ON income (user_id);

CREATE TABLE budgets (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    period_type VARCHAR(12) NOT NULL,
    year INTEGER NOT NULL,
    period_index INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_budgets_user_period_currency
        UNIQUE (user_id, period_type, year, period_index, currency),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_budgets_user_id ON budgets (user_id);
CREATE INDEX ix_budgets_user_year ON budgets (user_id, year);

CREATE TABLE invoices (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    document_id UUID,
    invoice_number VARCHAR(100),
    invoice_date DATE,
    due_date DATE,
    category VARCHAR(40),
    currency VARCHAR(3) NOT NULL,
    seller_name VARCHAR(255),
    buyer_name VARCHAR(255),
    seller_gstin VARCHAR(20),
    buyer_gstin VARCHAR(20),
    billing_address TEXT,
    shipping_address TEXT,
    place_of_supply VARCHAR(120),
    payment_terms VARCHAR(255),
    subtotal NUMERIC(14, 2),
    discount_total NUMERIC(14, 2),
    taxable_value NUMERIC(14, 2),
    cgst NUMERIC(14, 2),
    sgst NUMERIC(14, 2),
    igst NUMERIC(14, 2),
    cess NUMERIC(14, 2),
    other_charges NUMERIC(14, 2),
    round_off NUMERIC(14, 2),
    total NUMERIC(14, 2) NOT NULL,
    validation_warnings JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (document_id),
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE SET NULL
);
CREATE INDEX ix_invoices_user_date ON invoices (user_id, invoice_date);
CREATE INDEX ix_invoices_user_category ON invoices (user_id, category);
CREATE INDEX ix_invoices_user_seller_number
    ON invoices (user_id, seller_name, invoice_number);
CREATE INDEX ix_invoices_user_id ON invoices (user_id);

CREATE TABLE invoice_items (
    id UUID NOT NULL,
    invoice_id UUID NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(40),
    hsn_sac_code VARCHAR(40),
    quantity NUMERIC(14, 3),
    unit VARCHAR(30),
    unit_price NUMERIC(14, 2),
    discount NUMERIC(14, 2),
    taxable_amount NUMERIC(14, 2),
    gst_rate NUMERIC(6, 3),
    cgst NUMERIC(14, 2),
    sgst NUMERIC(14, 2),
    igst NUMERIC(14, 2),
    cess NUMERIC(14, 2),
    line_total NUMERIC(14, 2),
    PRIMARY KEY (id),
    FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
);
CREATE INDEX ix_invoice_items_invoice ON invoice_items (invoice_id);

CREATE TABLE reimbursement_teams (
    id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE reimbursement_memberships (
    id UUID NOT NULL,
    team_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(12) NOT NULL,
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_reimbursement_memberships_user UNIQUE (user_id),
    CONSTRAINT uq_reimbursement_memberships_team_user UNIQUE (team_id, user_id),
    FOREIGN KEY (team_id) REFERENCES reimbursement_teams (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_reimbursement_memberships_team
    ON reimbursement_memberships (team_id);
CREATE INDEX ix_reimbursement_memberships_user_id
    ON reimbursement_memberships (user_id);

-- Reimbursement categories defined by admin with claim limits
CREATE TABLE reimbursement_categories (
    id UUID NOT NULL,
    team_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    max_amount NUMERIC(14, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'INR',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_reimbursement_categories_team_name UNIQUE (team_id, name),
    FOREIGN KEY (team_id) REFERENCES reimbursement_teams (id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_reimbursement_categories_team ON reimbursement_categories (team_id);
CREATE INDEX ix_reimbursement_categories_active ON reimbursement_categories (team_id, is_active);

CREATE TABLE reimbursement_claims (
    id UUID NOT NULL,
    team_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    invoice_id UUID,
    category_id UUID,
    merchant_name VARCHAR(255) NOT NULL,
    expense_date DATE,
    description TEXT NOT NULL,
    category VARCHAR(40),
    amount NUMERIC(14, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'submitted',
    review_note TEXT,
    reviewer_id UUID,
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    paid_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_reimbursement_claims_invoice UNIQUE (invoice_id),
    FOREIGN KEY (team_id) REFERENCES reimbursement_teams (id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES reimbursement_categories (id) ON DELETE SET NULL,
    FOREIGN KEY (reviewer_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_reimbursement_claims_employee
    ON reimbursement_claims (employee_id);
CREATE INDEX ix_reimbursement_claims_team_status
    ON reimbursement_claims (team_id, status);
CREATE INDEX ix_reimbursement_claims_category ON reimbursement_claims (category_id);

-- User claims tracking per category per period (monthly/quarterly/yearly)
CREATE TABLE user_claims (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    category_id UUID NOT NULL,
    claim_id UUID NOT NULL,
    period_type VARCHAR(12) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    claimed_amount NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES reimbursement_categories (id) ON DELETE CASCADE,
    FOREIGN KEY (claim_id) REFERENCES reimbursement_claims (id) ON DELETE CASCADE
);
CREATE INDEX ix_user_claims_user_category_period
    ON user_claims (user_id, category_id, period_start, period_end);

INSERT INTO alembic_version (version_num) VALUES ('0010_reimbursement_categories');

-- Development-only seed accounts. Both must change their predictable
-- temporary ID password on first sign-in. Replace the example email addresses
-- and use new, private passwords before exposing this database to real users.
WITH seed_team AS (
    INSERT INTO reimbursement_teams (id, name, created_at)
    VALUES (gen_random_uuid(), 'XpenzIQ Admin Team', now())
    RETURNING id
),
seed_admin AS (
    INSERT INTO users (
        id, email, display_name, password_hash, employee_id,
        user_role, must_change_password, preferred_currency, created_at
    )
    VALUES (
        gen_random_uuid(),
        'admin@example.com',
        'Administrator',
        '$argon2id$v=19$m=65536,t=3,p=4$CJeIfQ6c/AbLiQZnxEFMvA$75vUZL9ajyYXnBzi5yzjdXThZY2x9bWBWzKlzBg/RwE',
        'ADMIN001',
        'admin',
        TRUE,
        'INR',
        now()
    )
    RETURNING id
),
seed_employee AS (
    INSERT INTO users (
        id, email, display_name, password_hash, employee_id,
        user_role, must_change_password, preferred_currency, created_at
    )
    VALUES (
        gen_random_uuid(),
        'employee@example.com',
        'Sample Employee',
        '$argon2id$v=19$m=65536,t=3,p=4$Ysiz9zvp01NkVnA1Y1sZ+Q$hxePQOZbd3fCbequ+WKcCyflDbI9cWLFyX3iQKZ+dKM',
        'EMP001',
        'user',
        TRUE,
        'INR',
        now()
    )
    RETURNING id
),
seed_category AS (
    INSERT INTO reimbursement_categories (
        id, team_id, name, description, max_amount, currency, is_active, created_at, created_by
    )
    SELECT
        gen_random_uuid(),
        seed_team.id,
        'Travel',
        'Business travel expenses including flights, hotels, and local transport',
        50000.00,
        'INR',
        TRUE,
        now(),
        seed_admin.id
    FROM seed_team CROSS JOIN seed_admin
    RETURNING id
),
seed_category2 AS (
    INSERT INTO reimbursement_categories (
        id, team_id, name, description, max_amount, currency, is_active, created_at, created_by
    )
    SELECT
        gen_random_uuid(),
        seed_team.id,
        'Meals',
        'Business meals and entertainment',
        15000.00,
        'INR',
        TRUE,
        now(),
        seed_admin.id
    FROM seed_team CROSS JOIN seed_admin
    RETURNING id
),
seed_category3 AS (
    INSERT INTO reimbursement_categories (
        id, team_id, name, description, max_amount, currency, is_active, created_at, created_by
    )
    SELECT
        gen_random_uuid(),
        seed_team.id,
        'Office Supplies',
        'Office supplies, software, and equipment',
        25000.00,
        'INR',
        TRUE,
        now(),
        seed_admin.id
    FROM seed_team CROSS JOIN seed_admin
    RETURNING id
)
INSERT INTO reimbursement_memberships (id, team_id, user_id, role, joined_at)
SELECT gen_random_uuid(), seed_team.id, seed_admin.id, 'owner', now()
FROM seed_team CROSS JOIN seed_admin
UNION ALL
SELECT gen_random_uuid(), seed_team.id, seed_employee.id, 'employee', now()
FROM seed_team CROSS JOIN seed_employee;

SELECT setval('employee_id_seq', 1, TRUE);

COMMIT;