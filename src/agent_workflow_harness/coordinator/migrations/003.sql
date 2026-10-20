-- SPDX-License-Identifier: Apache-2.0
CREATE TABLE awh_m1.integration_policies (
    project_id text PRIMARY KEY REFERENCES awh_m1.projects,
    policy_hash text NOT NULL,
    document jsonb NOT NULL
);
CREATE UNIQUE INDEX one_gateway_per_branch ON awh_m1.integration_policies
    ((document->>'repository'), (document->>'branch'));
CREATE TABLE awh_m1.integrations (
    project_id text NOT NULL REFERENCES awh_m1.projects,
    integration_id text NOT NULL,
    run_id text NOT NULL,
    execution_id text NOT NULL,
    state text NOT NULL CHECK (state IN ('validating','prepared','committed','aborted')),
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id,integration_id),
    FOREIGN KEY (project_id,run_id) REFERENCES awh_m1.runs,
    FOREIGN KEY (project_id,execution_id) REFERENCES awh_m1.executions
);
CREATE UNIQUE INDEX one_pending_git_effect ON awh_m1.integrations(project_id)
    WHERE state='prepared';
CREATE UNIQUE INDEX one_live_integration_per_execution
    ON awh_m1.integrations(project_id,execution_id) WHERE state<>'aborted';
CREATE UNIQUE INDEX one_live_integration_per_run
    ON awh_m1.integrations(project_id,run_id) WHERE state<>'aborted';
CREATE TABLE awh_m1.integration_reviews (
    project_id text NOT NULL REFERENCES awh_m1.projects,
    review_key text NOT NULL,
    approver text NOT NULL,
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id,review_key)
);
