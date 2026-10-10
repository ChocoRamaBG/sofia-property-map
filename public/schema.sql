-- Sofia property map schema. Import once in phpMyAdmin before importing seed files.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS data_sources (
  code VARCHAR(40) NOT NULL,
  label_bg VARCHAR(190) NOT NULL,
  label_en VARCHAR(190) NOT NULL,
  source_url VARCHAR(500) NULL,
  snapshot_file VARCHAR(255) NOT NULL,
  snapshot_date DATE NULL,
  PRIMARY KEY (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS data_imports (
  id VARCHAR(80) NOT NULL,
  source_code VARCHAR(40) NOT NULL,
  source_file VARCHAR(255) NOT NULL,
  imported_at DATETIME NOT NULL,
  records_loaded INT UNSIGNED NOT NULL DEFAULT 0,
  notes TEXT NULL,
  PRIMARY KEY (id),
  KEY idx_import_source_time (source_code, imported_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS parcels (
  cadastral_id VARCHAR(80) NOT NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  coordinate_source_file VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (cadastral_id),
  KEY idx_parcel_lat_lng (latitude, longitude)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS source_documents (
  source_code VARCHAR(40) NOT NULL,
  document_hash CHAR(64) NOT NULL,
  record_key VARCHAR(190) NULL,
  raw_fields LONGTEXT NOT NULL,
  snapshot_file VARCHAR(255) NOT NULL,
  imported_at DATETIME NOT NULL,
  PRIMARY KEY (source_code, document_hash),
  KEY idx_document_record (source_code, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS parcel_documents (
  parcel_cadastral_id VARCHAR(80) NOT NULL,
  source_code VARCHAR(40) NOT NULL,
  document_hash CHAR(64) NOT NULL,
  PRIMARY KEY (parcel_cadastral_id, source_code, document_hash),
  KEY idx_parcel_document (source_code, document_hash),
  CONSTRAINT fk_parcel_document_parcel FOREIGN KEY (parcel_cadastral_id)
    REFERENCES parcels (cadastral_id) ON DELETE CASCADE,
  CONSTRAINT fk_parcel_document_source FOREIGN KEY (source_code, document_hash)
    REFERENCES source_documents (source_code, document_hash) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
