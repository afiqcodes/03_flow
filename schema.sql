CREATE TABLE IF NOT EXISTS logbook_entries (
    id SERIAL PRIMARY KEY,
    entry_date DATE NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    location VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    day_type TEXT NOT NULL CHECK (day_type IN ('Work', 'Holiday', 'MeTIME', 'Family')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Restore the single day type if the multi-type Logbook schema was used.
-- Keep the extra columns and their data, but allow old-style inserts again.
ALTER TABLE logbook_entries ADD COLUMN IF NOT EXISTS day_type TEXT;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'logbook_entries'::regclass
          AND attname = 'day_types' AND NOT attisdropped
    ) THEN
        UPDATE logbook_entries SET day_type = day_types[1] WHERE day_type IS NULL;
        ALTER TABLE logbook_entries ALTER COLUMN day_types DROP NOT NULL;
    END IF;
END $$;
ALTER TABLE logbook_entries ALTER COLUMN day_type SET NOT NULL;
ALTER TABLE logbook_entries DROP CONSTRAINT IF EXISTS logbook_entries_day_type_check;
ALTER TABLE logbook_entries ADD CONSTRAINT logbook_entries_day_type_check
    CHECK (day_type IN ('Work', 'Holiday', 'MeTIME', 'Family'));

CREATE TABLE IF NOT EXISTS logbook_images (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES logbook_entries(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/gif', 'image/webp')),
    data BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS logbook_images_entry_id_idx ON logbook_images(entry_id);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at TIMESTAMP,
    priority TEXT NOT NULL DEFAULT 'Medium'
        CHECK (priority IN ('Low', 'Medium', 'High', 'Urgent')),
    difficulty TEXT NOT NULL DEFAULT 'Medium'
        CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    task_type TEXT NOT NULL DEFAULT 'Others'
        CHECK (task_type IN ('Work', 'Finance', 'Home', 'Personal', 'Health', 'Errands', 'Others')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    done BOOLEAN NOT NULL DEFAULT FALSE
);

-- Upgrade task tables created before metadata fields were introduced.
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS due_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'Medium'
        CHECK (priority IN ('Low', 'Medium', 'High', 'Urgent')),
    ADD COLUMN IF NOT EXISTS difficulty TEXT NOT NULL DEFAULT 'Medium'
        CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'Others'
        CHECK (task_type IN ('Work', 'Finance', 'Home', 'Personal', 'Health', 'Errands', 'Others')),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- Replace the previous task-type check and keep existing Study tasks visible.
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_task_type_check;
UPDATE tasks SET task_type = 'Others' WHERE task_type = 'Study';
ALTER TABLE tasks ADD CONSTRAINT tasks_task_type_check
    CHECK (task_type IN ('Work', 'Finance', 'Home', 'Personal', 'Health', 'Errands', 'Others'));

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    billing_cycle TEXT NOT NULL
        CHECK (billing_cycle IN ('monthly', 'yearly')),
    next_billing_date DATE NOT NULL,
    subscription_type TEXT NOT NULL DEFAULT 'Others'
        CHECK (subscription_type IN (
            'Gaming', 'Telecommunications', 'Streaming', 'Software', 'Finance',
            'Productivity', 'Education', 'Fitness', 'Work', 'Others'
        )),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Add categories to subscription tables created before this feature.
ALTER TABLE subscriptions
ADD COLUMN IF NOT EXISTS subscription_type TEXT NOT NULL DEFAULT 'Others'
CHECK (subscription_type IN (
    'Gaming', 'Telecommunications', 'Streaming', 'Software', 'Finance',
    'Productivity', 'Education', 'Fitness', 'Work', 'Others'
));

-- Remember the billing day after the first payment to avoid month-end date drift.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS billing_day SMALLINT
    CHECK (billing_day BETWEEN 1 AND 31);

CREATE TABLE IF NOT EXISTS bookmarks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    bookmark_type TEXT NOT NULL DEFAULT 'Others'
        CHECK (bookmark_type IN (
            'Gaming', 'Telecommunications', 'Streaming', 'Software', 'Finance',
            'Productivity', 'Education', 'Fitness', 'Work', 'Others'
        )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public_holiday_cache (
    year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    state_code VARCHAR(3) NOT NULL,
    holidays JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (year, state_code)
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Terminated', 'Ongoing', 'In Review', 'Completed')),
    github_url TEXT,
    website_url TEXT,
    image_filename TEXT,
    image_mime_type TEXT,
    image_data BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_files (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    data BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS project_files_project_id_idx ON project_files(project_id);

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL CHECK (length(btrim(title)) > 0),
    content TEXT NOT NULL CHECK (length(btrim(content)) > 0 AND length(content) <= 20000),
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS notes_project_id_idx ON notes(project_id);
CREATE INDEX IF NOT EXISTS notes_task_id_idx ON notes(task_id);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL CHECK (length(btrim(title)) > 0),
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    category TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    occurred_on DATE NOT NULL CHECK (EXTRACT(YEAR FROM occurred_on) BETWEEN 2000 AND 2200),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (kind = 'expense' AND category IN ('food', 'transport', 'bills', 'entertainment', 'others'))
        OR (kind = 'income' AND category IN ('salary', 'freelance', 'refunds', 'others'))
    )
);
CREATE INDEX IF NOT EXISTS transactions_occurred_on_idx ON transactions(occurred_on);

-- Link confirmed subscription payments while preserving expenses when a plan is removed.
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS subscription_id INTEGER
        REFERENCES subscriptions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_due_on DATE;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_subscription_expense_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_subscription_expense_check
    CHECK (subscription_due_on IS NULL OR kind = 'expense');
CREATE UNIQUE INDEX IF NOT EXISTS transactions_subscription_bill_idx
    ON transactions(subscription_id, subscription_due_on);

CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2200),
    month SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    income NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (income >= 0),
    savings NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (savings >= 0),
    food NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (food >= 0),
    transport NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (transport >= 0),
    bills NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (bills >= 0),
    entertainment NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (entertainment >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (year, month)
);

-- Upgrade budgets created with the earlier single-amount model.
ALTER TABLE budgets
    ADD COLUMN IF NOT EXISTS income NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (income >= 0),
    ADD COLUMN IF NOT EXISTS savings NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (savings >= 0),
    ADD COLUMN IF NOT EXISTS food NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (food >= 0),
    ADD COLUMN IF NOT EXISTS transport NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (transport >= 0),
    ADD COLUMN IF NOT EXISTS bills NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (bills >= 0),
    ADD COLUMN IF NOT EXISTS entertainment NUMERIC(12, 2)
        NOT NULL DEFAULT 0 CHECK (entertainment >= 0);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'amount'
    ) THEN
        EXECUTE 'UPDATE budgets SET income = amount '
             || 'WHERE income = 0 AND amount > 0';
    END IF;
END $$;

ALTER TABLE budgets DROP COLUMN IF EXISTS amount;

-- Preserve databases created by the earlier, misspelled draft.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'subscriptions'
          AND column_name = 'next_biling_date'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'subscriptions'
          AND column_name = 'next_billing_date'
    ) THEN
        ALTER TABLE subscriptions
        RENAME COLUMN next_biling_date TO next_billing_date;
    END IF;
END $$;
