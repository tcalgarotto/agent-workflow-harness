-- SPDX-License-Identifier: Apache-2.0
-- Trusted-supervisor execution admission; no container control in the API.
CREATE TABLE awh_m1.executions (
    project_id text NOT NULL,
    execution_id text NOT NULL,
    run_id text NOT NULL,
    manifest_hash text NOT NULL,
    owner text NOT NULL,
    state text NOT NULL CHECK (state IN ('admitted','stopped')),
    outcome text,
    receipt_hash text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    stopped_at timestamptz,
    PRIMARY KEY (project_id,execution_id),
    FOREIGN KEY (project_id,run_id) REFERENCES awh_m1.runs
);
CREATE UNIQUE INDEX one_unstopped_execution ON awh_m1.executions(project_id,run_id)
    WHERE state='admitted';
