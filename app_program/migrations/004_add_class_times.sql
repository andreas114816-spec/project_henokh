ALTER TABLE classes
    ADD COLUMN start_time TIME NULL,
    ADD COLUMN end_time TIME NULL,
    ADD COLUMN start_presence TIME NULL,
    ADD COLUMN end_presence TIME NULL;
