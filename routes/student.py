# routes/student.py — Updated to use student_required from utils/auth.py
from flask import Blueprint, render_template, request, session as sesh, jsonify, redirect, url_for, flash
from extensions import mongo
from utils.auth import student_required  # ← Now importing the centralised decorator
from utils.sessions import get_current_context, get_active_enrollments, find_student_by_admission, get_active_session
import bcrypt

student_bp = Blueprint('student', __name__, url_prefix='/student')

# ==================== STUDENT LOGIN ====================
@student_bp.route('/login', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        adm_no = request.form['admission_number'].strip()
        password = request.form['password'].encode('utf-8')

        student = mongo.students.find_one({'admission_number': adm_no})

        if student and bcrypt.checkpw(password, student['password'].encode('utf-8')):
            # Fetch current term enrollment to check visibility
            current_session = get_current_context()['session_name'] # Make dynamic or from config
            current_term = get_current_context()['term']

            enrollment = mongo.term_enrollments.find_one({
                'admission_number': adm_no,
                'session': current_session,
                'term': current_term
            })

            if not enrollment or not enrollment.get('results_visible', True):
                flash('Your results are currently hidden by administration. Contact the school for access.', 'error')
                return render_template('student/search.html')

            # Login success
            sesh['adm_no'] = student['admission_number']
            sesh['student_name'] = student['name']
            sesh['role'] = 'student'
            return redirect(url_for('student.dashboard'))

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
    adm_no = sesh['adm_no']
    current_session = get_current_context()['session_name']
    current_term = get_current_context()["term"]
    available_terms = ['First', 'Second', 'Third']
    # Double-check visibility on every dashboard load
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': current_session,
        'term': current_term
    })

    if not enrollment or not enrollment.get('results_visible', True):
        flash('Your results are currently hidden by administration.', 'error')
        sesh.clear()
        return redirect(url_for('student.search'))

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
    current_session = get_current_context()['session_name']
    current_term = get_current_context()['term']

    session_name = get_current_context()['session_name']
    term_name = get_current_context()['term']
    
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': current_session,
        'term': current_term
    })

    if not enrollment or not enrollment.get('results_visible', True):
        return jsonify({'error': 'Results are currently hidden by administration'}), 403

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