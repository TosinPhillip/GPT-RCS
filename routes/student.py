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
        password = request.form['password'].encode('utf-8')

        student = mongo.students.find_one({'admission_number': adm_no})
        if student and bcrypt.checkpw(password, student['password'].encode('utf-8')):
            # Check if blocked
            if not student.get('results_visible', True):
                flash('Your results are currently unavailable. Contact administration.', 'error')
                return render_template('student/login.html')

            
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
    return redirect(url_for('student.login'))

# ==================== DASHBOARD / RESULT VIEWER ====================
@student_bp.route('/dashboard')
@student_required
def dashboard():
    
    adm_no = sesh['adm_no']
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
        student_sessions=student_sessions,
        selected_session=selected_session,
        grouped_results=results,
        student_name=sesh['student_name']
    )

# ==================== AJAX RESULT FETCH ====================
# routes/student.py — /results route (clean, safe, no slash issues)

@student_bp.route('/results')
@student_required
def get_results():
    student = mongo.students.find_one({'admission_number': sesh['adm_no']})
    
    if not student.get('results_visible', True):
        return render_template('student/blocked.html')
    try:
        session_name = request.args.get('session')
        term_name = request.args.get('term')
    
        if not session_name or not term_name:
            return jsonify({'error': 'Session and term required'}), 400
    
        admission_number = sesh['adm_no']
    
        subject_results = list(mongo.results.find({
            'admission_number': admission_number,
            'session': session_name,
            'term': term_name
        }).sort('subject'))
    
        if not subject_results:
            return jsonify({'results': []})
    
        subjects = []
        grand_total = 0
    
        for res in subject_results:
            ca1 = res.get('ca1', 0)
            ca2 = res.get('ca2', 0)
            exam = res.get('exam', 0)
            cum1 = res.get('cumulative1', 0)
            cum2 = res.get('cumulative2', 0)
    
            if term_name == 'Third':
                subject_total = round((cum1 + cum2 + ca1 + ca2 + exam) / 3, 2)
            else:
                subject_total = ca1 + ca2 + exam
    
            grand_total += subject_total
    
            subjects.append({
                'subject': res['subject'],
                'ca1': ca1,
                'ca2': ca2,
                'exam': exam,
                'cumulative1': cum1,
                'cumulative2': cum2,
                'total': subject_total,
                'position': res.get('position'),
                'class_average': res.get('class_average')
            })
    
        comment_doc = mongo.results.find_one({
            'admission_number': admission_number,
            'session': session_name,
            'term': term_name,
            'teacher_comment': {'$exists': True}
        })
    
        average = round(grand_total / len(subjects), 2) if subjects else 0
        class_average = subjects[0].get('class_average') if subjects else None
    
        result_doc = {
            'subjects': subjects,
            'grand_total': round(grand_total, 2),
            'average': average,
            'class_average': class_average,
            'teacher_comment': comment_doc.get('teacher_comment') if comment_doc else None,
        }
    
        return jsonify({'results': [result_doc]})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500