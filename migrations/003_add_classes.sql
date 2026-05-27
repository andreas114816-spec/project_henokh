CREATE TABLE IF NOT EXISTS classes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    class_code VARCHAR(40) NOT NULL UNIQUE,
    teacher_id INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_classes_class_code (class_code),
    CONSTRAINT fk_classes_teacher_id
        FOREIGN KEY (teacher_id) REFERENCES teachers(id)
        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS class_students (
    class_id INT NOT NULL,
    student_id INT NOT NULL,
    PRIMARY KEY (class_id, student_id),
    CONSTRAINT fk_class_students_class_id
        FOREIGN KEY (class_id) REFERENCES classes(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_class_students_student_id
        FOREIGN KEY (student_id) REFERENCES students(id)
        ON DELETE CASCADE
);
