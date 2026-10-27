-- Local profile password accounts.
CREATE TABLE IF NOT EXISTS local_credentials (
	profile_id VARCHAR(36) NOT NULL REFERENCES profiles (id),
	login VARCHAR(320) NOT NULL UNIQUE,
	password_hash VARCHAR(200) NOT NULL,
	PRIMARY KEY (profile_id)
);
