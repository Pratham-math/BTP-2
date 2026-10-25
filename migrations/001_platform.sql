-- Generated baseline; apply once to an empty BTP2 database.

CREATE TABLE profiles (
	id VARCHAR(36) NOT NULL,
	email VARCHAR(320) NOT NULL,
	display_name VARCHAR(120) NOT NULL,
	privilege VARCHAR(16) NOT NULL,
	active BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE audit_events (
	actor_id VARCHAR(36) NOT NULL,
	action VARCHAR(60) NOT NULL,
	target_id VARCHAR(36) NOT NULL,
	details JSON NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES profiles (id)
);

CREATE TABLE courses (
	owner_id VARCHAR(36) NOT NULL,
	title VARCHAR(160) NOT NULL,
	enrollment_hash VARCHAR(64),
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES profiles (id),
	UNIQUE (enrollment_hash)
);

CREATE INDEX ix_courses_owner_id ON courses (owner_id);

CREATE TABLE jobs (
	owner_id VARCHAR(36) NOT NULL,
	dedup_key VARCHAR(64) NOT NULL,
	kind VARCHAR(24) NOT NULL,
	priority INTEGER NOT NULL,
	payload JSON NOT NULL,
	state VARCHAR(24) NOT NULL,
	stage VARCHAR(60) NOT NULL,
	lease_until FLOAT,
	fence INTEGER NOT NULL,
	failures INTEGER NOT NULL,
	error_code VARCHAR(60),
	result JSON NOT NULL,
	consumers JSON NOT NULL,
	updated_at FLOAT NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES profiles (id),
	UNIQUE (dedup_key)
);

CREATE INDEX ix_job_claim ON jobs (state, priority, created_at);

CREATE INDEX ix_jobs_owner_id ON jobs (owner_id);

CREATE TABLE lessons (
	owner_id VARCHAR(36) NOT NULL,
	course_id VARCHAR(36),
	title VARCHAR(160) NOT NULL,
	retired BOOLEAN NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES profiles (id),
	FOREIGN KEY(course_id) REFERENCES courses (id)
);

CREATE INDEX ix_lessons_course_id ON lessons (course_id);

CREATE INDEX ix_lessons_owner_id ON lessons (owner_id);

CREATE TABLE memberships (
	course_id VARCHAR(36) NOT NULL,
	user_id VARCHAR(36) NOT NULL,
	active BOOLEAN NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (course_id, user_id),
	FOREIGN KEY(course_id) REFERENCES courses (id),
	FOREIGN KEY(user_id) REFERENCES profiles (id)
);

CREATE INDEX ix_memberships_course_id ON memberships (course_id);

CREATE INDEX ix_memberships_user_id ON memberships (user_id);

CREATE TABLE sources (
	owner_id VARCHAR(36) NOT NULL,
	course_id VARCHAR(36),
	title VARCHAR(160) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	state VARCHAR(24) NOT NULL,
	object_key TEXT,
	current_version INTEGER NOT NULL,
	metadata_json JSON NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_id) REFERENCES profiles (id),
	FOREIGN KEY(course_id) REFERENCES courses (id)
);

CREATE INDEX ix_sources_owner_id ON sources (owner_id);

CREATE TABLE stage_results (
	job_id VARCHAR(36) NOT NULL,
	stage VARCHAR(64) NOT NULL,
	input_hash VARCHAR(64) NOT NULL,
	output JSON NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (job_id, stage, input_hash),
	FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_stage_results_job_id ON stage_results (job_id);

CREATE TABLE curricula (
	lesson_id VARCHAR(36) NOT NULL,
	number INTEGER NOT NULL,
	blueprint JSON NOT NULL,
	availability VARCHAR(32) NOT NULL,
	publication VARCHAR(24) NOT NULL,
	confirmed BOOLEAN NOT NULL,
	manifest_revision INTEGER NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (lesson_id, number),
	FOREIGN KEY(lesson_id) REFERENCES lessons (id)
);

CREATE INDEX ix_curricula_lesson_id ON curricula (lesson_id);

CREATE TABLE source_versions (
	source_id VARCHAR(36) NOT NULL,
	number INTEGER NOT NULL,
	evidence JSON NOT NULL,
	warnings JSON NOT NULL,
	confirmed BOOLEAN NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (source_id, number),
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

CREATE INDEX ix_source_versions_source_id ON source_versions (source_id);

CREATE TABLE assessments (
	curriculum_id VARCHAR(36) NOT NULL,
	objective_id VARCHAR(64) NOT NULL,
	variant VARCHAR(16) NOT NULL,
	public JSON NOT NULL,
	private JSON NOT NULL,
	validated BOOLEAN NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (curriculum_id, objective_id, variant),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id)
);

CREATE INDEX ix_assessments_curriculum_id ON assessments (curriculum_id);

CREATE TABLE assignments (
	course_id VARCHAR(36) NOT NULL,
	curriculum_id VARCHAR(36) NOT NULL,
	due_at FLOAT,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(course_id) REFERENCES courses (id),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id)
);

CREATE INDEX ix_assignments_course_id ON assignments (course_id);

CREATE TABLE blocks (
	curriculum_id VARCHAR(36) NOT NULL,
	objective_id VARCHAR(64) NOT NULL,
	profile VARCHAR(24) NOT NULL,
	context_hash VARCHAR(64) NOT NULL,
	state VARCHAR(24) NOT NULL,
	script JSON NOT NULL,
	verification JSON NOT NULL,
	checksum VARCHAR(64),
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (curriculum_id, objective_id, profile, context_hash),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id)
);

CREATE INDEX ix_blocks_curriculum_id ON blocks (curriculum_id);

CREATE TABLE issues (
	user_id VARCHAR(36) NOT NULL,
	curriculum_id VARCHAR(36) NOT NULL,
	category VARCHAR(24) NOT NULL,
	description TEXT NOT NULL,
	resolved BOOLEAN NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES profiles (id),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id)
);

CREATE INDEX ix_issues_user_id ON issues (user_id);

CREATE TABLE reviews (
	curriculum_id VARCHAR(36) NOT NULL,
	reviewer_id VARCHAR(36) NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	approved BOOLEAN NOT NULL,
	findings JSON NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id),
	FOREIGN KEY(reviewer_id) REFERENCES profiles (id)
);

CREATE INDEX ix_reviews_curriculum_id ON reviews (curriculum_id);

CREATE TABLE assets (
	block_id VARCHAR(36) NOT NULL,
	position INTEGER NOT NULL,
	kind VARCHAR(16) NOT NULL,
	object_key TEXT NOT NULL,
	checksum VARCHAR(64) NOT NULL,
	duration FLOAT NOT NULL,
	mime VARCHAR(80) NOT NULL,
	transcript TEXT NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (block_id, position, kind),
	FOREIGN KEY(block_id) REFERENCES blocks (id)
);

CREATE INDEX ix_assets_block_id ON assets (block_id);

CREATE TABLE learning_sessions (
	user_id VARCHAR(36) NOT NULL,
	curriculum_id VARCHAR(36) NOT NULL,
	assignment_id VARCHAR(36),
	selected_block_id VARCHAR(36),
	objective_id VARCHAR(64) NOT NULL,
	variant VARCHAR(16) NOT NULL,
	state VARCHAR(32) NOT NULL,
	revision INTEGER NOT NULL,
	route_revision INTEGER NOT NULL,
	position JSON NOT NULL,
	evidence JSON NOT NULL,
	continuation_job_id VARCHAR(36),
	manifest_revision INTEGER NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES profiles (id),
	FOREIGN KEY(curriculum_id) REFERENCES curricula (id),
	FOREIGN KEY(assignment_id) REFERENCES assignments (id),
	FOREIGN KEY(selected_block_id) REFERENCES blocks (id)
);

CREATE INDEX ix_learning_sessions_user_id ON learning_sessions (user_id);

CREATE TABLE attempts (
	user_id VARCHAR(36) NOT NULL,
	session_id VARCHAR(36) NOT NULL,
	assessment_id VARCHAR(36) NOT NULL,
	idempotency_key VARCHAR(80) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	answer JSON NOT NULL,
	state VARCHAR(24) NOT NULL,
	result JSON NOT NULL,
	route_revision INTEGER NOT NULL,
	id VARCHAR(36) NOT NULL,
	created_at FLOAT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (user_id, idempotency_key),
	FOREIGN KEY(user_id) REFERENCES profiles (id),
	FOREIGN KEY(session_id) REFERENCES learning_sessions (id),
	FOREIGN KEY(assessment_id) REFERENCES assessments (id)
);

CREATE INDEX ix_attempts_session_id ON attempts (session_id);

CREATE INDEX ix_attempts_user_id ON attempts (user_id);
