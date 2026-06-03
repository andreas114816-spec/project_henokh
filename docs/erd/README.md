# Henokh Project ERD

This ERD is based on `models/db_models.py` and uses Mermaid crow's-foot notation.

## Visual Diagram

Open `henokh_erd.svg` to view the rendered diagram.

```mermaid
erDiagram
    USERS {
        int id PK
        string username UK
        string password_hash "column: password"
        datetime created_at
    }

    APP_SETTINGS {
        int id PK
        string key UK
        string value
        datetime updated_at
    }

    TEACHERS {
        int id PK
        string name
        string NIP UK
        string subject "nullable"
        datetime deleted_at "nullable"
        datetime created_at
    }

    STUDENTS {
        int id PK
        string name
        string NIM UK
        json face_embeddings "nullable"
        datetime deleted_at "nullable"
        datetime created_at
        datetime updated_at
    }

    CLASSES {
        int id PK
        string name
        string class_code UK
        int teacher_id FK "nullable"
        time start_time "nullable"
        time end_time "nullable"
        time start_presence "nullable"
        time end_presence "nullable"
        datetime deleted_at "nullable"
        datetime created_at
        datetime updated_at
    }

    CLASS_STUDENTS {
        int class_id PK,FK
        int student_id PK,FK
    }

    ATTENDANCES {
        int id PK
        int class_id FK
        int student_id FK
        date attendance_date
        string status
        datetime presence_at
        datetime created_at
        datetime updated_at
        string unique_class_student_date "class_id + student_id + attendance_date"
    }

    TEACHERS ||--o{ CLASSES : teaches
    CLASSES ||--o{ CLASS_STUDENTS : has
    STUDENTS ||--o{ CLASS_STUDENTS : enrolls
    CLASSES ||--o{ ATTENDANCES : records
    STUDENTS ||--o{ ATTENDANCES : has
```

## Relationship Notes

- One teacher can teach zero or many classes.
- A class can have zero or many students through `class_students`.
- A student can join zero or many classes through `class_students`.
- A class can have zero or many attendance records.
- A student can have zero or many attendance records.
- `attendances` has a unique constraint on `class_id`, `student_id`, and `attendance_date`.
