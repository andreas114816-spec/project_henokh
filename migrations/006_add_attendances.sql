CREATE TABLE IF NOT EXISTS attendances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    class_id INT NOT NULL,
    student_id INT NOT NULL,
    attendance_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    presence_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_attendance_class_student_date (class_id, student_id, attendance_date),
    INDEX ix_attendances_class_id (class_id),
    INDEX ix_attendances_student_id (student_id),
    INDEX ix_attendances_attendance_date (attendance_date),
    CONSTRAINT fk_attendances_class_id
        FOREIGN KEY (class_id) REFERENCES classes(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_attendances_student_id
        FOREIGN KEY (student_id) REFERENCES students(id)
        ON DELETE CASCADE
);
