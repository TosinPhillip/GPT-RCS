# utils/session.py
from extensions import mongo
from flask import abort

def get_active_session():
    session = mongo.sessions.find_one({"active": True})
    if not session:
        abort(400, "No active session configured. Please contact admin.")
    return session

def get_active_term(session_doc=None):
    session = session_doc or get_active_session()
    active_term = next((t for t in session['terms'] if t['active']), None)
    if not active_term:
        abort(400, "No active term in current session.")
    return active_term['name']

def get_current_context():
    session = get_active_session()
    term = get_active_term(session)
    return {
        "session_name": session['name'],
        "term": term,
        "session_doc": session
    }

def get_active_enrollments():
    """Returns students enrolled in CURRENT active session/term"""
    ctx = get_current_context()
    enrollments = list(mongo.enrollments.find({
        "session": ctx["session_name"],
        "term": ctx["term"],
        "status": "active"
    }).sort("class_", 1))
    
    # Enrich with student core data
    for e in enrollments:
        student = mongo.students.find_one({"_id": e["student_id"]})
        e["student_name"] = student["name"] if student else "Unknown"
        e["admission_number"] = student["admission_number"] if student else ""
    
    return enrollments

def find_student_by_admission(adm_no):
    """Find core student by timeless admission number"""
    return mongo.students.find_one({"admission_number": adm_no})