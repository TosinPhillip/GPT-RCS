# models/result.py
from datetime import datetime
from extensions import mongo  # Optional: only if you need direct DB access here


def validate_result(data):
    required = ['student_id', 'session', 'term', 'subjects']
    for field in required:
        if field not in data:
            raise ValueError(f"Missing {field}")
    if not isinstance(data['subjects'], list) or len(data['subjects']) == 0:
        raise ValueError("Subjects must be a non-empty list")
    for subj in data['subjects']:
        if 'name' not in subj or 'score' not in subj:
            raise ValueError("Each subject must have name and score")
    return data

def upload_result(db, data):
    validated = validate_result(data)
    validated['uploaded_at'] = datetime.utcnow()
    
    # Prevent duplicates
    existing = db.results.find_one({
        'student_id': validated['student_id'],
        'session': validated['session'],
        'term': validated['term']
    })
    if existing:
        raise ValueError("Result already exists for this student, session, and term")
    
    # Return the InsertOneResult
    result = db.results.insert_one(validated)
    return result  # ← This has .inserted_id

def update_result(db, filter_q, update_data):
    return db.results.update_one(filter_q, update_data)