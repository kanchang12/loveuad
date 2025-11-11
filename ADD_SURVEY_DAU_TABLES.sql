-- Feature 1: Anonymous Monthly Caregiver Burden Survey
-- Stores only anonymous code, completion date, and result bucket
CREATE TABLE IF NOT EXISTS survey_responses (
    id SERIAL PRIMARY KEY,
    code_hash VARCHAR(64) NOT NULL,  -- 17-digit code hashed for anonymity
    completion_date DATE NOT NULL,
    result_bucket VARCHAR(20) NOT NULL CHECK (result_bucket IN ('Low', 'Medium', 'High')),
    survey_day INT NOT NULL,  -- Day 30, 60, 90, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code_hash, survey_day)  -- One survey per milestone per code
);

CREATE INDEX idx_survey_completion ON survey_responses(completion_date);
CREATE INDEX idx_survey_bucket ON survey_responses(result_bucket);

-- Feature 2: Cumulative Daily Active User (DAU) Tracking
-- Stores only aggregated counts, NO individual codes
CREATE TABLE IF NOT EXISTS daily_active_users (
    id SERIAL PRIMARY KEY,
    event_date DATE NOT NULL,
    event_hour INT NOT NULL CHECK (event_hour >= 0 AND event_hour < 24),
    launch_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_date, event_hour)
);

CREATE INDEX idx_dau_date ON daily_active_users(event_date);

-- Temporary table for tracking unique launches per day (discarded after aggregation)
-- This allows us to check "has this code launched today" without storing the code long-term
CREATE TABLE IF NOT EXISTS daily_launch_tracker (
    code_hash VARCHAR(64) NOT NULL,
    launch_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(code_hash, launch_date)
);

-- Auto-cleanup: Delete records older than 2 days (we only need today's data)
CREATE INDEX idx_launch_tracker_date ON daily_launch_tracker(launch_date);

COMMENT ON TABLE survey_responses IS 'Anonymous survey responses - NO PII stored, only code hash and result bucket';
COMMENT ON TABLE daily_active_users IS 'Aggregated DAU counts - NO individual user data, only hourly totals';
COMMENT ON TABLE daily_launch_tracker IS 'Temporary launch tracking - auto-cleaned after 48 hours';
