# routes/student.py — Updated to use student_required from utils/auth.py

from flask import Blueprint, render_template, request, session as sesh, jsonify, redirect, url_for, flash
from extensions import mongo
from utils.auth import student_required  # ← Now importing the centralised decorator
import bcrypt

student_bp = Blueprint('student', __name__, url_prefix='/student')

# ==================== STUDENT LOGIN ====================
@student_bp.route('/login', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        adm_no = request.form['admission_number'].strip()
        password = request.form['password'].encode('utf-8')  # Plain text → bytes

        student = mongo.students.find_one({'admission_number': adm_no})

        if student:
            stored_hash = student['password']  

            # Convert stored hash string to bytes only once
            if bcrypt.checkpw(password, stored_hash.encode('utf-8')):
                # Check if results are blocked
                if not student.get('results_visible', True):
                    flash('Your results are currently unavailable. Contact administration.', 'error')
                    return render_template('student/search.html') 
                # Successful login
                sesh['adm_no'] = student['admission_number']
                sesh['student_name'] = student['name']
                sesh['role'] = 'student'
                return redirect(url_for('student.dashboard'))

        # If we get here: either no student or wrong password
        flash('Invalid admission number or password', 'error')

    return render_template('student/search.html')

# ==================== LOGOUT ====================
@student_bp.route('/logout')
def logout():
    sesh.clear()
    return redirect(url_for('student.search'))

# ==================== DASHBOARD / RESULT VIEWER ====================
@student_bp.route('/dashboard')
@student_required
def dashboard():
    available_terms = ['First', 'Second', 'Third']  # Or fetch dynamically
    adm_no = sesh['adm_no']
    student = mongo.students.find_one({'admission_number': adm_no})
    # Get all sessions this student has results in
    student_sessions = sorted(
        set(r['session'] for r in mongo.results.find({'admission_number': adm_no}, {'session': 1}))
    )

    # Default to latest session
    selected_session = request.args.get('session', student_sessions[-1] if student_sessions else None)

    results = {}
    if selected_session:
        raw = list(mongo.results.find({
            'admission_number': adm_no,
            'session': selected_session
        }).sort('term', 1))

        for r in raw:
            results.setdefault(r['term'], []).append(r)

    return render_template(
        'student/dashboard.html',
        sessions=student_sessions,
        terms=available_terms,
        selected_session=selected_session,
        grouped_results=results,
        student=student,
        student_name=sesh['student_name']
    )

# ==================== AJAX RESULT FETCH ====================
# routes/student.py — /results route (clean, safe, no slash issues)

@student_bp.route('/results')
@student_required
def get_results():
    adm_no = sesh['adm_no']
    session_name = request.args.get('session')
    term_name = request.args.get('term')

    if not session_name or not term_name:
        return jsonify({'error': 'Session and term are required'}), 400

    # Fetch all subject-level results for this session + term
    subject_docs = list(mongo.results.find({
        'admission_number': adm_no,
        'session': session_name,
        'term': term_name
    }).sort('subject', 1))

    if not subject_docs:
        return jsonify({'results': []})

    subjects = []
    grand_total = 0.0

    for doc in subject_docs:
        ca1   = float(doc.get('ca1', 0))
        ca2   = float(doc.get('ca2', 0))
        exam  = float(doc.get('exam', 0))
        cum1  = float(doc.get('cumulative1', 0))
        cum2  = float(doc.get('cumulative2', 0))

        if term_name == 'Third':
            subject_total = round((cum1 + cum2 + ca1 + ca2 + exam) / 3, 2)
        else:
            subject_total = ca1 + ca2 + exam

        grand_total += subject_total

        subjects.append({
            'subject':      doc.get('subject', 'Unknown'),
            'ca1':          ca1,
            'ca2':          ca2,
            'exam':         exam,
            'cumulative1':  cum1,
            'cumulative2':  cum2,
            'total':        subject_total,
            'position':     doc.get('position', '—'),
        })

    # Take metadata from the first document (assuming it's consistent across subjects)
    first_doc = subject_docs[0]
    average         = round(grand_total / len(subjects), 2) if subjects else 0
    class_average   = first_doc.get('class_average')
    overall_position = first_doc.get('overall_position')
    teacher_comment = first_doc.get('teacher_comment')  # or from any doc that has it

    result_payload = {
        'subjects':         subjects,
        'grand_total':      round(grand_total, 2),
        'average':          average,
        'class_average':    class_average,
        'overall_position': overall_position,
        'teacher_comment':  teacher_comment,
    }

    return jsonify({'results': [result_payload]})