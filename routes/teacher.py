# routes/teacher.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session as sesh
from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, SubmitField
from wtforms.validators import DataRequired, NumberRange
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
    sessions = list(mongo.sessions.find({}, {'name': 1, '_id': 0}))
    assignments = list(mongo.teacher_assignments.find(
        {'teacher_id': teacher_id},
        {'session': 1, 'class': 1, 'subject': 1, '_id': 0}
    ))
    session_map = {}
    for a in assignments:
        sess = a['session']
        if sess not in session_map:
            session_map[sess] = []
        session_map[sess].append({'class': a['class'], 'subject': a['subject']})

    # Add class teacher assignments
    class_assignments = list(mongo.class_teachers.find(
        {'teacher_id': teacher_id},
        {'session': 1, 'class': 1, '_id': 0}
    ))

    return render_template(
        'teacher/dashboard.html',
        sessions=sessions,
        session_map=session_map,
        class_assignments=class_assignments
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

@teacher_bp.route('/upload/<class_>/<subject>', methods=['GET', 'POST'])
@teacher_required
def upload_form(class_, subject):
    session = request.args.get('session')  # Required; add validation below
    if not session:
        flash('Missing session', 'error')
        return redirect(url_for('teacher.dashboard'))
    # Verify assignment
    teacher_id = ObjectId(sesh['user_id'])
    assignment = mongo.teacher_assignments.find_one({
        'teacher_id': teacher_id,
        'session': session,
        'class': class_,
        'subject': subject
    })
    if not assignment:
        flash('You are not assigned to this class/subject', 'error')
        return redirect(url_for('teacher.dashboard'))

    students = list(mongo.students.find(
        {'class': class_},
        {'admission_number': 1, 'name': 1, '_id': 1}
    ).sort('name'))

    # Load enrollments
    enrollment_doc = mongo.student_subjects.find_one({'session': session, 'class_': class_})
    enrolled_student_ids = enrollment_doc['subjects'][subject] if enrollment_doc and subject in enrollment_doc.get('subjects', {}) else []

    terms = list(mongo.terms.find({}, {'name': 1, '_id': 0}).sort('order'))

    form = ScoreForm()
    form.term.choices = [(t['name'], t['name']) for t in terms]

    saved_term = None
    summary_results = []

    if request.method == 'POST':
        form.process(data=request.form)
        term = request.form.get('term')
        if not term:
            flash('Please select a term', 'error')
        else:
            selected_student_ids = request.form.getlist('enrolled_students')

            # Save enrollments
            mongo.student_subjects.update_one(
                {'session': session, 'class': class_},
                {'$set': {f'subjects.{subject}': selected_student_ids}},
                upsert=True
            )

            results_to_save = []
            for student_id in selected_student_ids:
                prefix = f'score_{student_id}_'
                ca1 = int(request.form.get(prefix + 'ca1', 0))
                ca2 = int(request.form.get(prefix + 'ca2', 0))
                exam = int(request.form.get(prefix + 'exam', 0))
                cumulative1 = int(request.form.get(prefix + 'cumulative1', 0)) if term == 'Third' else 0
                cumulative2 = int(request.form.get(prefix + 'cumulative2', 0)) if term == 'Third' else 0

                if term == 'Third':
                    term_total = ca1 + ca2 + exam
                    final_total = round((cumulative1 + cumulative2 + term_total) / 3, 2)
                else:
                    final_total = ca1 + ca2 + exam

                results_to_save.append({
                    'student_id': ObjectId(student_id),
                    'total': final_total,
                    'ca1': ca1, 'ca2': ca2, 'exam': exam,
                    'cumulative1': cumulative1, 'cumulative2': cumulative2
                })

                mongo.results.update_one(
                    {'student_id': ObjectId(student_id), 'session': session, 'class': class_, 'subject': subject, 'term': term},
                    {'$set': {
                        'ca1': ca1, 'ca2': ca2, 'exam': exam,
                        'cumulative1': cumulative1, 'cumulative2': cumulative2,
                        'total': final_total
                    }},
                    upsert=True
                )

            if results_to_save:
                results_to_save.sort(key=lambda x: x['total'], reverse=True)
                class_average = round(sum(r['total'] for r in results_to_save) / len(results_to_save), 2)
                for rank, res in enumerate(results_to_save, 1):
                    mongo.results.update_one(
                        {'student_id': res['student_id'], 'session': session, 'class': class_, 'subject': subject, 'term': term},
                        {'$set': {'position': rank, 'class_average': class_average}}
                    )

            flash(f'Scores saved successfully for {term} Term!', 'success')
            saved_term = term

    # After save or on GET: load summary if term selected/saved
    current_term = saved_term or request.args.get('term') or (terms[0]['name'] if terms else None)
    if current_term:
        summary_results = list(mongo.results.find({
            'session': session,
            'class': class_,
            'subject': subject,
            'term': current_term
        }).sort('total', -1))

        for res in summary_results:
            student = mongo.students.find_one({'_id': res['student_id']})
            res['student_name'] = student['name'] if student else 'Unknown'

    return render_template(
        'teacher/upload_form.html',
        session=session,
        class_=class_,
        subject=subject,
        students=students,
        enrolled_student_ids=[str(s) for s in enrolled_student_ids],
        terms=terms,
        form=form,
        summary_results=summary_results,
        current_term=current_term,
        class_average=summary_results[0]['class_average'] if summary_results else None
    )
    

@teacher_bp.route('/class_teacher/<class_>')
@teacher_required
def class_teacher_form(class_):
    session = request.args.get('session')  # Required; add validation below
    if not session:
        flash('Missing session', 'error')
        return redirect(url_for('teacher.dashboard'))
    
    teacher_id = ObjectId(sesh['user_id'])
    assignment = mongo.class_teachers.find_one({
        'teacher_id': teacher_id,
        'session': session,
        'class': class_
    })
    if not assignment:
        flash('Not assigned as class teacher for this session/class', 'error')
        return redirect(url_for('teacher.dashboard'))
    
    students = list(mongo.students.find({'class': class_}, {'admission_number': 1, 'name': 1, '_id': 0}).sort('name'))
    terms = list(mongo.terms.find({}, {'name': 1, '_id': 0}).sort('order'))
    return render_template('teacher/class_teacher.html', session=session, class_=class_, students=students, terms=terms)

@teacher_bp.route('/class_teacher/update', methods=['POST'])
@teacher_required
def class_teacher_update():
    data = request.get_json()
    session_name = data['session']
    class_name = data['class']
    term = data['term']
    updates = data['updates']  # [{adm_no, comment, attendance, psychomotor}]

    for u in updates:
        student = mongo.students.find_one({'admission_number': u['adm_no']})
        if not student:
            continue
        mongo.results.update_one(
            {'student_id': student['_id'], 'session': session_name, 'term': term},
            {'$set': {
                'teacher_comment': u['comment'],
                'attendance': u['attendance'],
                'psychomotor': u['psychomotor']
            }},
            upsert=True
        )

    return jsonify({'status': 'success'})