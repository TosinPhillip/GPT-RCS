# routes/student.py
from flask import Blueprint, render_template, request, jsonify, session , redirect, url_for
from extensions import mongo
from bson import ObjectId
import bcrypt

student_bp = Blueprint('student', __name__)

@student_bp.route('/', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        adm_no = request.form.get('admission_number')
        password = request.form.get('password')
        if not adm_no or not password:
            return jsonify({'error': 'Admission number and password required'}), 400

        student = mongo.students.find_one({'admission_number': adm_no.strip()})
        if not student or not bcrypt.checkpw(password.encode('utf-8'), student.get('password', '').encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        session['student_id'] = str(student['_id'])
        return redirect(url_for('student.dashboard'))

    return render_template('student/search.html')

@student_bp.route('/dashboard')
def dashboard():
    if 'student_id' not in session:
        return redirect(url_for('student.search'))

    student = mongo.students.find_one({'_id': ObjectId(session['student_id'])})
    sessions = list(mongo.sessions.find({}, {'name': 1, '_id': 0}).sort('name'))
    terms = list(mongo.terms.find({}, {'name': 1, '_id': 0}).sort('order'))

    return render_template('student/dashboard.html', student=student, sessions=sessions, terms=terms)

@student_bp.route('/results')
def results():
    if 'student_id' not in session:
        return jsonify({'error': 'Please login'}), 401

    session_name = request.args.get('session')
    term = request.args.get('term')
    student_id = ObjectId(session['student_id'])

    if not session_name or not term:
        return jsonify({'error': 'Select session and term'}), 400

    # Calculate position
    results = list(mongo.results.find({'session': session_name, 'term': term}))
    totals = []
    for r in results:
        total = sum((s.get('score_CA1', 0) + s.get('score_CA2', 0) + s.get('score_Exam', 0)) for s in r['subjects'])
        totals.append({'student_id': r['student_id'], 'total': total})

    totals.sort(key=lambda x: x['total'], reverse=True)
    position = next((i + 1 for i, t in enumerate(totals) if t['student_id'] == student_id), None)

    result = mongo.results.find_one({
        'student_id': student_id,
        'session': session_name,
        'term': term
    })
    if not result:
        return jsonify({'results': []})

    result['position'] = position
    return jsonify({'results': [result]})