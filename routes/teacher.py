# routes/teacher.py
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo
from utils.auth import teacher_required
from models.result import upload_result
from datetime import datetime
from bson import ObjectId
import bcrypt
import json

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')

# ==================== TEACHER LOGIN ====================
@teacher_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        user = mongo.users.find_one({'username': username, 'role': 'teacher'})
        if user and bcrypt.checkpw(password, user['password'].encode('utf-8')):
            session['user_id'] = str(user['_id'])
            session['role'] = 'teacher'
            session['username'] = username
            return redirect(url_for('teacher.dashboard'))
        flash('Invalid credentials', 'error')

    return render_template('teacher/login.html')

# ==================== LOGOUT ====================
@teacher_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('teacher.login'))

# ==================== DASHBOARD ====================
@teacher_bp.route('/dashboard')
@teacher_required
def dashboard():
    teacher_id = ObjectId(session['user_id'])

    # Get active sessions
    sessions = list(mongo.sessions.find({}, {'name': 1, '_id': 0}))

    # Get assignments for this teacher
    assignments = list(mongo.teacher_assignments.find(
        {'teacher_id': teacher_id},
        {'session': 1, 'class': 1, 'subject': 1}
    ))

    # Group by session
    session_map = {}
    for a in assignments:
        sess = a['session']
        if sess not in session_map:
            session_map[sess] = []
        session_map[sess].append({'class': a['class'], 'subject': a['subject']})

    return render_template(
        'teacher/dashboard.html',
        sessions=sessions,
        session_map=session_map
    )

# ==================== UPLOAD RESULT ====================
# routes/teacher.py
@teacher_bp.route('/api/students')
@teacher_required
def api_students():
    cls = request.args.get('class')
    if not cls:
        return jsonify([])

    students = list(mongo.students.find(
        {'class': cls},
        {'admission_number': 1, 'name': 1, '_id': 0}
    ))
    return jsonify(students)

@teacher_bp.route('/upload/<session>/<class>/<subject>')
@teacher_required
def upload_form(session, class_, subject):
    # Verify assignment
    teacher_id = ObjectId(session['user_id'])
    assignment = mongo.teacher_assignments.find_one({
        'teacher_id': teacher_id,
        'session': session,
        'class': class_,
        'subject': subject
    })
    if not assignment:
        flash('You are not assigned to this class/subject', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Get students in class
    students = list(mongo.students.find(
        {'class': class_},
        {'admission_number': 1, 'name': 1, '_id': 0}
    ).sort('name'))

    terms = list(mongo.terms.find({}, {'name': 1, '_id': 0}).sort('order'))

    return render_template(
        'teacher/upload_form.html',
        session=session,
        class_=class_,
        subject=subject,
        students=students,
        terms=terms
    )