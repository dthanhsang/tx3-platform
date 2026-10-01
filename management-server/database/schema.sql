-- TX3 Remote Management Platform - Database Schema
-- PostgreSQL 15+
-- Version: 1.0.0

-- ============================================================
-- EXTENSIONS
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ORGANIZATIONS
-- ============================================================
CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    username        VARCHAR(100) NOT NULL UNIQUE,
    email           VARCHAR(255) UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(255),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled', 'locked')),
    failed_logins   INT NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    last_login      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- ROLES & PERMISSIONS
-- ============================================================
CREATE TABLE roles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(50) NOT NULL UNIQUE
                    CHECK (name IN ('owner', 'admin', 'technician', 'viewer')),
    description     TEXT
);

INSERT INTO roles (name, description) VALUES
    ('owner', 'Full system access'),
    ('admin', 'Device management, remote, files, ADB, user management'),
    ('technician', 'Remote, files, limited ADB, scoped to assigned sites'),
    ('viewer', 'View device status only');

CREATE TABLE user_roles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    scope_type      VARCHAR(20) DEFAULT 'global'
                    CHECK (scope_type IN ('global', 'organization', 'site', 'device')),
    scope_id        UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, role_id, scope_type, scope_id)
);

-- ============================================================
-- LICENSES
-- ============================================================
CREATE TABLE licenses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    license_key_hash VARCHAR(255) NOT NULL UNIQUE,
    plan            VARCHAR(50) NOT NULL DEFAULT 'standard'
                    CHECK (plan IN ('trial', 'standard', 'professional', 'enterprise')),
    max_devices     INT NOT NULL DEFAULT 10,
    features        JSONB NOT NULL DEFAULT '{}',
    expires_at      TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'expired', 'revoked')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- DEVICES
-- ============================================================
CREATE TABLE devices (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_uuid     VARCHAR(64) NOT NULL UNIQUE,
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    device_name     VARCHAR(255),
    mac_wifi        VARCHAR(17),
    mac_ethernet    VARCHAR(17),
    serial          VARCHAR(100),
    android_id      VARCHAR(64),
    model           VARCHAR(100),
    soc             VARCHAR(50),
    ram_mb          INT,
    rom_version     VARCHAR(50),
    agent_version   VARCHAR(50),
    protocol_version INT DEFAULT 1,
    wg_ip           INET,
    wg_public_key   VARCHAR(44),
    hardware_fingerprint VARCHAR(255),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'online', 'offline', 'disabled', 'revoked')),
    last_seen       TIMESTAMPTZ,
    last_heartbeat  JSONB,
    uptime_seconds  BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_devices_org ON devices(organization_id);
CREATE INDEX idx_devices_status ON devices(status);
CREATE INDEX idx_devices_wg_ip ON devices(wg_ip);
CREATE INDEX idx_devices_last_seen ON devices(last_seen);

-- ============================================================
-- DEVICE LOCATIONS
-- ============================================================
CREATE TABLE device_locations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id       UUID NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
    customer        VARCHAR(255),
    site            VARCHAR(255),
    building        VARCHAR(100),
    floor           VARCHAR(20),
    room            VARCHAR(50),
    address_text    TEXT,
    note            TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_device_locations_search ON device_locations
    USING gin(to_tsvector('simple',
        coalesce(customer,'') || ' ' || coalesce(site,'') || ' ' ||
        coalesce(building,'') || ' ' || coalesce(floor,'') || ' ' ||
        coalesce(room,'') || ' ' || coalesce(note,'')));

-- ============================================================
-- TAGS
-- ============================================================
CREATE TABLE tags (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    UNIQUE(organization_id, name)
);

CREATE TABLE device_tags (
    device_id       UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    tag_id          UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (device_id, tag_id)
);

-- ============================================================
-- WIREGUARD PEERS (server-side)
-- ============================================================
CREATE TABLE wg_peers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id       UUID NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
    public_key      VARCHAR(44) NOT NULL UNIQUE,
    assigned_ip     INET NOT NULL UNIQUE,
    preshared_key_hash VARCHAR(255),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'revoked', 'rotating')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at      TIMESTAMPTZ
);

-- ============================================================
-- REMOTE SESSIONS
-- ============================================================
CREATE TABLE remote_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    device_id       UUID NOT NULL REFERENCES devices(id),
    session_type    VARCHAR(20) NOT NULL DEFAULT 'remote'
                    CHECK (session_type IN ('remote', 'file', 'adb')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    duration_seconds INT,
    result          VARCHAR(20) DEFAULT 'active'
                    CHECK (result IN ('active', 'completed', 'error', 'timeout', 'cancelled')),
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX idx_remote_sessions_device ON remote_sessions(device_id, started_at);
CREATE INDEX idx_remote_sessions_user ON remote_sessions(user_id, started_at);

-- ============================================================
-- FILE TRANSFERS
-- ============================================================
CREATE TABLE transfers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    device_id       UUID NOT NULL REFERENCES devices(id),
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('upload', 'download')),
    filename        VARCHAR(1024) NOT NULL,
    file_size       BIGINT NOT NULL,
    transferred     BIGINT NOT NULL DEFAULT 0,
    hash_sha256     VARCHAR(64),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'active', 'paused', 'completed', 'failed', 'cancelled')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'
);

-- ============================================================
-- AUDIT LOGS
-- ============================================================
CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    device_id       UUID REFERENCES devices(id),
    action          VARCHAR(100) NOT NULL,
    category        VARCHAR(50) NOT NULL DEFAULT 'general'
                    CHECK (category IN ('auth', 'device', 'remote', 'file', 'adb', 'admin', 'general')),
    severity        VARCHAR(10) NOT NULL DEFAULT 'info'
                    CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    ip_address      INET,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, created_at);
CREATE INDEX idx_audit_logs_device ON audit_logs(device_id, created_at);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);

-- ============================================================
-- TELEMETRY (partitioned by month for retention)
-- ============================================================
CREATE TABLE telemetry (
    id              UUID NOT NULL DEFAULT uuid_generate_v4(),
    device_id       UUID NOT NULL REFERENCES devices(id),
    cpu_percent     REAL,
    ram_used_mb     INT,
    ram_total_mb    INT,
    temperature_c   REAL,
    storage_used_mb BIGINT,
    storage_total_mb BIGINT,
    network_rx_bps  BIGINT,
    network_tx_bps  BIGINT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Create partitions for first 3 months
CREATE TABLE telemetry_2026_10 PARTITION OF telemetry
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE telemetry_2026_11 PARTITION OF telemetry
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE telemetry_2026_12 PARTITION OF telemetry
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

-- ============================================================
-- SESSION TOKENS
-- ============================================================
CREATE TABLE session_tokens (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(255) NOT NULL UNIQUE,
    device_info     VARCHAR(255),
    ip_address      INET,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_session_tokens_user ON session_tokens(user_id);
CREATE INDEX idx_session_tokens_expires ON session_tokens(expires_at);

-- ============================================================
-- PROVISIONING TOKENS (one-time bootstrap)
-- ============================================================
CREATE TABLE provisioning_tokens (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    token_hash      VARCHAR(255) NOT NULL UNIQUE,
    max_uses        INT NOT NULL DEFAULT 100,
    used_count      INT NOT NULL DEFAULT 0,
    expires_at      TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'exhausted', 'expired', 'revoked')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- BATCH OPERATIONS
-- ============================================================
CREATE TABLE batch_operations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    operation_type  VARCHAR(50) NOT NULL,
    target_devices  UUID[] NOT NULL,
    total_count     INT NOT NULL,
    completed_count INT NOT NULL DEFAULT 0,
    failed_count    INT NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')),
    payload         JSONB DEFAULT '{}',
    results         JSONB DEFAULT '[]',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ============================================================
-- FUNCTIONS
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_organizations_updated BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER tr_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER tr_licenses_updated BEFORE UPDATE ON licenses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER tr_devices_updated BEFORE UPDATE ON devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER tr_device_locations_updated BEFORE UPDATE ON device_locations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
