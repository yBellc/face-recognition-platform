-- ============================================================
-- 人脸识别系统数据库 schema
-- 方案第五部分：数据库设计
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------
-- 一、projects 项目或案件隔离空间
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    purpose         TEXT,
    data_policy     TEXT,
    retention_days  INTEGER DEFAULT 365,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 账号与项目级授权（生产环境必须先初始化这些表）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(64) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(32) NOT NULL DEFAULT 'reviewer',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_access (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id      BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role            VARCHAR(32) NOT NULL DEFAULT 'reviewer',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_project_access_user ON project_access(user_id);
CREATE INDEX IF NOT EXISTS idx_project_access_project ON project_access(project_id);

CREATE TABLE IF NOT EXISTS threshold_profiles (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    high            REAL NOT NULL DEFAULT 0.75,
    medium          REAL NOT NULL DEFAULT 0.60,
    low             REAL NOT NULL DEFAULT 0.45,
    source          VARCHAR(64) NOT NULL DEFAULT 'default_demo',
    sample_count    INTEGER NOT NULL DEFAULT 0,
    calibrated_at   TIMESTAMPTZ,
    notes           TEXT,
    UNIQUE (project_id)
);

-- ------------------------------------------------------------
-- 二、subjects 匿名人员表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subjects (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_code       VARCHAR(64) NOT NULL,   -- Person_017 之类
    display_name        VARCHAR(255),
    authorization_status VARCHAR(32) DEFAULT 'authorized',
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, external_code)
);
CREATE INDEX IF NOT EXISTS idx_subjects_project ON subjects(project_id);

-- ------------------------------------------------------------
-- 人脸照片处理授权记录
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consent_records (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_id      BIGINT REFERENCES subjects(id) ON DELETE CASCADE,
    consent_ref     VARCHAR(255) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'valid',
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_consent_project ON consent_records(project_id);
CREATE INDEX IF NOT EXISTS idx_consent_subject ON consent_records(subject_id);

-- ------------------------------------------------------------
-- 三、reference_images 参考照片表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reference_images (
    id              BIGSERIAL PRIMARY KEY,
    subject_id      BIGINT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    object_uri      VARCHAR(1024) NOT NULL,
    source_type     VARCHAR(32) DEFAULT 'authorized_upload',
    capture_session VARCHAR(128),
    quality_score   REAL,
    consent_ref     VARCHAR(255),
    sha256          VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ref_subject ON reference_images(subject_id);

-- ------------------------------------------------------------
-- 四、probe_images 待比对图片表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS probe_images (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_uri          VARCHAR(1024) NOT NULL,
    source_type         VARCHAR(32) DEFAULT 'folder',
    capture_time        TIMESTAMPTZ,
    camera_id           VARCHAR(64),
    sha256              VARCHAR(64),
    processing_status   VARCHAR(32) DEFAULT 'pending',
    error_message       TEXT,
    processing_ms       INTEGER,
    archived_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE probe_images ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_probe_project ON probe_images(project_id);
CREATE INDEX IF NOT EXISTS idx_probe_status ON probe_images(processing_status);
CREATE INDEX IF NOT EXISTS idx_probe_archived ON probe_images(archived_at);

-- ------------------------------------------------------------
-- 五、face_detections 每张图片中的人脸检测结果
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_detections (
    id              BIGSERIAL PRIMARY KEY,
    probe_image_id  BIGINT NOT NULL REFERENCES probe_images(id) ON DELETE CASCADE,
    reference_image_id BIGINT REFERENCES reference_images(id) ON DELETE CASCADE,
    owner_type      VARCHAR(16) NOT NULL,  -- 'probe' or 'reference'
    bbox            JSONB NOT NULL,        -- {x,y,w,h}
    landmarks       JSONB,                 -- 5 点关键点
    detector_score  REAL,
    quality_score   REAL,
    blur_score      REAL,
    pose            JSONB,                 -- {yaw, pitch, roll}
    occlusion_score REAL,
    usable          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_det_probe ON face_detections(probe_image_id);
CREATE INDEX IF NOT EXISTS idx_det_ref ON face_detections(reference_image_id);

-- ------------------------------------------------------------
-- 六、embeddings 特征向量表
-- 向量维度默认 512（ArcFace/Buffalo-L 常见）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embeddings (
    id              BIGSERIAL PRIMARY KEY,
    owner_type      VARCHAR(16) NOT NULL,  -- 'reference' or 'probe'
    owner_id        BIGINT NOT NULL,       -- face_detection.id
    model_version   VARCHAR(64) NOT NULL,
    vector          vector(512) NOT NULL,
    norm            REAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_emb_owner ON embeddings(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model_version);
-- ivfflat 余弦相似度索引（数据量上来后再 build）
-- CREATE INDEX ON embeddings USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);

-- ------------------------------------------------------------
-- 七、match_candidates 候选结果表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_candidates (
    id              BIGSERIAL PRIMARY KEY,
    probe_face_id   BIGINT NOT NULL REFERENCES face_detections(id) ON DELETE CASCADE,
    subject_id      BIGINT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    similarity      REAL NOT NULL,
    rank            INTEGER NOT NULL,
    decision_band   VARCHAR(16) DEFAULT 'low',  -- high/medium/low
    status          VARCHAR(32) DEFAULT 'pending', -- pending/confirmed/excluded/uncertain
    review_id       BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cand_face ON match_candidates(probe_face_id);
CREATE INDEX IF NOT EXISTS idx_cand_subject ON match_candidates(subject_id);
CREATE INDEX IF NOT EXISTS idx_cand_status ON match_candidates(status);

-- ------------------------------------------------------------
-- 八、review_tasks 人工复核任务
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_tasks (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT NOT NULL REFERENCES match_candidates(id) ON DELETE CASCADE,
    reviewer_id     VARCHAR(64),
    decision        VARCHAR(32),             -- confirm/exclude/uncertain
    reason          TEXT,
    evidence_uri    VARCHAR(1024),
    reviewed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_review_cand ON review_tasks(candidate_id);

-- ------------------------------------------------------------
-- 九、model_versions 模型注册表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    id                  BIGSERIAL PRIMARY KEY,
    version_tag         VARCHAR(64) UNIQUE NOT NULL,
    detector_name       VARCHAR(128),
    recognizer_name     VARCHAR(128),
    weights_hash        VARCHAR(64),
    preprocessing       JSONB,
    threshold_profile   JSONB,                -- {high, medium, low}
    release_note        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 十、evaluation_runs 评测实验记录
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id                  BIGSERIAL PRIMARY KEY,
    dataset_name        VARCHAR(128) NOT NULL,
    split_definition    TEXT,
    model_version       VARCHAR(64) NOT NULL,
    metrics_json        JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 审计日志
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    actor       VARCHAR(64),
    action      VARCHAR(64) NOT NULL,
    resource    VARCHAR(256),
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

-- ------------------------------------------------------------
-- 初始化默认项目和模型版本
-- ------------------------------------------------------------
INSERT INTO projects (name, purpose, retention_days, status)
VALUES ('default', '默认原型项目', 365, 'active')
ON CONFLICT DO NOTHING;

INSERT INTO model_versions (version_tag, detector_name, recognizer_name,
                            preprocessing, threshold_profile, release_note)
VALUES (
    'insightface-buffalo-l-v1',
    'SCRFD_10G_KPS',
    'ArcFace_Buffalo_L',
    '{"align_size": 112, "norm": "l2"}'::jsonb,
    '{"high": 0.75, "medium": 0.60, "low": 0.45}'::jsonb,
    '第一版默认：InsightFace buffalo_l 模型'
)
ON CONFLICT DO NOTHING;
