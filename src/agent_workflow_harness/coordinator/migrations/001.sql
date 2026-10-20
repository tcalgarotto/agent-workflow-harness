-- SPDX-License-Identifier: Apache-2.0
CREATE TABLE awh_m1.projects (
    project_id text PRIMARY KEY,
    document jsonb NOT NULL,
    spent bigint NOT NULL DEFAULT 0 CHECK (spent >= 0),
    reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
    CHECK (spent + reserved <= (document->>'budget_limit')::bigint)
);
CREATE TABLE awh_m1.tasks (
    project_id text NOT NULL REFERENCES awh_m1.projects,
    task_id text NOT NULL,
    document jsonb NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    accepted_revision bigint,
    contract_hash text,
    state text NOT NULL CHECK (state IN
      ('proposed','ready','running','submitted','reconciling','completed','cancelled')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    spent bigint NOT NULL DEFAULT 0 CHECK (spent >= 0),
    reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    PRIMARY KEY (project_id, task_id),
    CHECK (spent + reserved <= (document->>'budget_limit')::bigint)
);
CREATE TABLE awh_m1.dependencies (
    project_id text NOT NULL,
    task_id text NOT NULL,
    dependency_id text NOT NULL,
    PRIMARY KEY (project_id, task_id, dependency_id),
    FOREIGN KEY (project_id,task_id) REFERENCES awh_m1.tasks,
    FOREIGN KEY (project_id,dependency_id) REFERENCES awh_m1.tasks,
    CHECK (task_id <> dependency_id)
);
CREATE TABLE awh_m1.runs (
    project_id text NOT NULL,
    run_id text NOT NULL,
    task_id text NOT NULL,
    owner text NOT NULL,
    fence bigint NOT NULL,
    accepted_revision bigint NOT NULL,
    contract_hash text NOT NULL,
    state text NOT NULL CHECK (state IN ('active','submitted','expired','revoked','reconciled')),
    lease_until timestamptz NOT NULL,
    deadline timestamptz NOT NULL,
    allocated bigint NOT NULL CHECK (allocated > 0),
    spent bigint NOT NULL DEFAULT 0 CHECK (spent >= 0 AND spent <= allocated),
    artifact_ref text,
    PRIMARY KEY (project_id,run_id),
    UNIQUE (project_id,fence),
    FOREIGN KEY (project_id,task_id) REFERENCES awh_m1.tasks
);
CREATE UNIQUE INDEX one_unresolved_run ON awh_m1.runs (project_id,task_id)
    WHERE state IN ('active','expired','revoked');
CREATE TABLE awh_m1.reservations (
    project_id text NOT NULL,
    run_id text NOT NULL,
    resource text NOT NULL,
    PRIMARY KEY (project_id,run_id,resource),
    FOREIGN KEY (project_id,run_id) REFERENCES awh_m1.runs
);
CREATE TABLE awh_m1.budget_ledger (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id text NOT NULL,
    run_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('reserve','charge','release','burn')),
    units bigint NOT NULL CHECK (units >= 0),
    command_id text NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id,run_id) REFERENCES awh_m1.runs
);
CREATE TABLE awh_m1.outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id text NOT NULL REFERENCES awh_m1.projects,
    kind text NOT NULL,
    actor text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX outbox_project_cursor ON awh_m1.outbox (project_id,id);
CREATE TABLE awh_m1.commands (
    project_id text NOT NULL REFERENCES awh_m1.projects,
    actor text NOT NULL,
    command_id text NOT NULL,
    request_hash text NOT NULL,
    response jsonb NOT NULL,
    PRIMARY KEY (project_id,actor,command_id)
);
