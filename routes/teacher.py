from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session as sesh
from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from extensions import mongo
from utils.auth import teacher_required
from utils.sessions import get_current_context, get_active_enrollments, find_student_by_admission
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
            sesh['user_id'] = str(user['_id'])
            sesh['role'] = 'teacher'
            sesh['username'] = username
            return redirect(url_for('teacher.dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('teacher/login.html')
# ==================== LOGOUT ====================
@teacher_bp.route('/logout')
def logout():
    sesh.clear()
    return redirect(url_for('teacher.login'))
# ==================== DASHBOARD ====================
@teacher_bp.route('/dashboard')
@teacher_required
def dashboard():
    teacher_id = ObjectId(sesh['user_id'])
    ctx = get_current_context()  # Active session/term

    # Subject assignments in active session
    assignments = list(mongo.teacher_assignments.find({
        'teacher_id': teacher_id,
        'session': ctx['session_name']
    }))

    session_map = {}
    for a in assignments:
        session_map.setdefault(ctx['session_name'], []).append({
            'class': a['class'],
            'subject': a['subject']
        })

    # Class teacher role in active session
    class_assignment = list(mongo.class_teachers.find({
        'teacher_id': teacher_id,
        'session': ctx['session_name']
    }))

    return render_template(
        'teacher/dashboard.html',
        session_name=ctx['session_name'],
        term=ctx['term'],
        session_map=session_map,
        class_assignment=class_assignment  # {'class': 'JSS1'} or None
    )
# ==================== UPLOAD RESULT ====================
# New Form for Scores (per student, but we'll use dynamic in template)
class ScoreForm(FlaskForm):
    ca1 = IntegerField('CA1 (15)', validators=[DataRequired(), NumberRange(0, 15)])
    ca2 = IntegerField('CA2 (15)', validators=[DataRequired(), NumberRange(0, 15)])
    exam = IntegerField('Exam (70)', validators=[DataRequired(), NumberRange(0, 70)])
    cumulative1 = IntegerField('Cumulative First Term', validators=[NumberRange(0, 100)])
    cumulative2 = IntegerField('Cumulative Second Term', validators=[NumberRange(0, 100)])
    term = SelectField('Term', validators=[DataRequired()])
    submit = SubmitField('Save Scores')
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


@teacher_bp.route('/upload/<class_>/<subject>')
@teacher_required
def upload_form(class_, subject):
    teacher_id = ObjectId(sesh['user_id'])
    ctx = get_current_context()

    # Verify assignment in active session
    assignment = mongo.teacher_assignments.find_one({
        'teacher_id': teacher_id,
        'session': ctx['session_name'],
        'class': class_,
        'subject': subject
    })
    if not assignment:
        flash('Not assigned to this class/subject this session', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Students enrolled in this class AND offering this subject
    enrolled_students = list(mongo.enrollments.find({
        'session': ctx['session_name'],
        'term': ctx['term'],
        'class_': class_,
        'subjects': subject,
        'status': 'active'
    }))

    student_ids = [e['student_id'] for e in enrolled_students]
    students = list(mongo.students.find({'_id': {'$in': student_ids}}).sort('name'))

    terms = [{'name': ctx['term']}]  # Only current term

    return render_template(
        'teacher/upload_form.html',
        session=ctx['session_name'],
        term=ctx['term'],
        class_=class_,
        subject=subject,
        students=students,
        terms=terms
    )

    
@teacher_bp.route('/class_teacher/<class_>')
@teacher_required
def class_teacher_form(class_):
    teacher_id = ObjectId(sesh['user_id'])
    ctx = get_current_context()

    assignment = mongo.class_teachers.find_one({
        'teacher_id': teacher_id,
        'session': ctx['session_name'],
        'class': class_
    })
    if not assignment:
        flash('Not assigned as class teacher this session', 'error')
        return redirect(url_for('teacher.dashboard'))

    # All active students in this class
    enrolled = list(mongo.enrollments.find({
        'session': ctx['session_name'],
        'term': ctx['term'],
        'class_': class_,
        'status': 'active'
    }))
    student_ids = [e['student_id'] for e in enrolled]
    students = list(mongo.students.find({'_id': {'$in': student_ids}}).sort('name'))

    return render_template(
        'teacher/class_teacher.html',
        session=ctx['session_name'],
        term=ctx['term'],
        class_=class_,
        students=students
    )   


@teacher_bp.route('/class_teacher/update', methods=['POST'])
@teacher_required
def class_teacher_update():
    data = request.get_json()
    session_name = data['session']
    class_name = data['class']
    term = data['term']
    updates = data['updates'] # [{adm_no, comment, attendance, psychomotor}]
    for u in updates:
        mongo.results.update_one(
            {'admission_number': u['adm_no'], 'session': session_name, 'term': term},
            {'$set': {
                'teacher_comment': u['comment'],
                'attendance': u['attendance'],
                'psychomotor': u['psychomotor']
            }},
            upsert=True
        )
    return jsonify({'status': 'success'})