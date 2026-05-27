CREATE TABLE IF NOT EXISTS app_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `key` VARCHAR(80) NOT NULL UNIQUE,
    value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_app_settings_key (`key`)
);

INSERT INTO app_settings (`key`, value)
SELECT 'anti_spoof_enabled', 'true'
WHERE NOT EXISTS (
    SELECT 1 FROM app_settings WHERE `key` = 'anti_spoof_enabled'
);
