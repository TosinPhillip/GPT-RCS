# routes/student.py — Updated to use student_required from utils/auth.py
from flask import Blueprint, render_template, request, session as sesh, jsonify, redirect, url_for, flash
from extensions import mongo
from utils.auth import student_required, calculate_position_in_class, calculate_subject_position
from utils.sessions import get_current_context, get_active_enrollments, find_student_by_admission, get_active_session
import bcrypt, re

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
    position, class_size = calculate_position_in_class(adm_no, selected_session, current_term)

    return render_template(
        'student/dashboard.html',
        no_in_class=class_size,
        sessions=student_sessions,
        terms=available_terms,
        selected_session=selected_session,
        grouped_results=results,
        student=student,
        student_name=sesh['student_name'],
        position_in_class=position,
        current_term=current_term,
        results=results
    )

# ==================== AJAX RESULT FETCH ====================
# routes/student.py — /results route (clean, safe, no slash issues)

import re

@student_bp.route('/results')
@student_required
def get_results():
    adm_no = sesh['adm_no']
    session_name = request.args.get('session')
    term_name = request.args.get('term')

    if not session_name or not term_name:
        return jsonify({'error': 'Session and term are required'}), 400

    # Visibility check
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': session_name,
        'term': term_name
    })
    if not enrollment or not enrollment.get('results_visible', True):
        return jsonify({'error': 'Results are currently hidden by administration'}), 403

    # Fetch subject's results
    subject_docs = list(mongo.results.find({
        'admission_number': adm_no,
        'session': session_name,
        'term': term_name
    }).sort('subject', 1))

    if not subject_docs:
        return jsonify({'results': [], 'message': f"No results for {term_name} Term yet."})

    subjects = []
    grand_total = 0.0

    for doc in subject_docs:
        subject_name = doc.get('subject', '').strip()
        ca1 = float(doc.get('ca1', 0))
        ca2 = float(doc.get('ca2', 0))
        exam = float(doc.get('exam', 0))

        # Cumulative logic for Third Term
        if term_name == 'Third':
            first = mongo.results.find_one({
                'admission_number': adm_no,
                'session': session_name,
                'term': 'First',
                'subject': {'$regex': re.escape(subject_name), '$options': 'i'}
            }) or {}
            second = mongo.results.find_one({
                'admission_number': adm_no,
                'session': session_name,
                'term': 'Second',
                'subject': {'$regex': re.escape(subject_name), '$options': 'i'}
            }) or {}
            cum1 = float(first.get('total', 0))
            cum2 = float(second.get('total', 0))
            subject_total = round((cum1 + cum2 + ca1 + ca2 + exam) / 3, 2)
        else:
            subject_total = round(ca1 + ca2 + exam, 2)

        grand_total += subject_total

        # Calculate Subject Position
        subject_position = calculate_subject_position(adm_no, subject_name, session_name, term_name)

        subjects.append({
            'subject': subject_name,
            'ca1': ca1,
            'ca2': ca2,
            'exam': exam,
            'total': subject_total,
            'grade': doc.get('grade', '—'),
            'remark': doc.get('remark', ''),
            'position': subject_position
        })

    # Overall Position
    overall_position, class_size = calculate_position_in_class(adm_no, session_name, term_name)

    # Teacher Comment
    profile = mongo.student_term_profiles.find_one({
        'admission_number': adm_no,
        'session': session_name,
        'term': term_name
    }) or {}
    teacher_comment = profile.get('class_teacher_comment', '')

    result_payload = {
        'subjects': subjects,
        'grand_total': round(grand_total, 2),
        'average': round(grand_total / len(subjects), 2) if subjects else 0,
        'overall_position': overall_position,
        'class_size': class_size,
        'teacher_comment': teacher_comment
    }

    return jsonify({'results': [result_payload]})