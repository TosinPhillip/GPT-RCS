# models/result.py
from datetime import datetime
from extensions import mongo  # Optional: only if you need direct DB access here


def validate_result(data):
    """
    Validate the structure of a result document.
    Now uses 'admission_number' instead of 'student_id' for student identification.
    """
    required = ['admission_number', 'session', 'term', 'subjects']
    for field in required:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(data['subjects'], list) or len(data['subjects']) == 0:
        raise ValueError("Subjects must be a non-empty list")

    for subj in data['subjects']:
        if 'name' not in subj or 'score' not in subj:
            raise ValueError("Each subject must have 'name' and 'score'")

    return data


def upload_result(db, data):
    """
    Upload a new complete result record for a student.
    Uses admission_number as the unique student identifier.
    Prevents duplicate uploads for the same student/session/term.
    """
    validated = validate_result(data)
    validated['uploaded_at'] = datetime.utcnow()

    # Prevent duplicates based on admission_number, session, and term
    existing = db.results.find_one({
        'admission_number': validated['admission_number'],
        'session': validated['session'],
        'term': validated['term']
    })

    if existing:
        raise ValueError(
            "Result already exists for this admission number, session, and term"
        )

    # Insert the new result
    result = db.results.insert_one(validated)
    return result  # Returns InsertOneResult with .inserted_id


def update_result(db, filter_q, update_data):
    """
    Update an existing result record.
    filter_q should typically include 'admission_number' for accurate targeting.
    """
    return db.results.update_one(filter_q, update_data)