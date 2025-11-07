# routes/admin.py
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo  # ← Fixed: no more import from app
from models.result import upload_result
from utils.auth import admin_required
import bcrypt
import csv
from datetime import datetime
from io import StringIO
from flask import request, jsonify


admin_bp = Blueprint('admin', __name__)

# Hardcoded admin
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = bcrypt.hashpw("gptschool2025".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        if username == ADMIN_USERNAME and bcrypt.checkpw(password, ADMIN_PASSWORD_HASH.encode('utf-8')):
            session['admin_logged_in'] = True
            return redirect(url_for('admin.upload'))
        else:
            flash('Invalid credentials', 'error')

    return render_template('admin/login.html')

@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('student.search'))

@admin_bp.route('/upload', methods=['GET', 'POST'])
@admin_required
def upload():
    if request.method == 'POST':
        data = request.json
        try:
            adm_no = data['admission_number']
            student = mongo.students.find_one({'admission_number': adm_no})
            if not student:
                return jsonify({'error': 'Student not found'}), 404

            result_data = {
                'student_id': student['_id'],
                'session': data['session'],
                'term': data['term'],
                'subjects': data['subjects']
            }
            result = upload_result(mongo.db, result_data)
            return jsonify({'status': 'success', 'result_id': str(result.inserted_id)})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    return render_template('admin/upload.html')

# routes/admin.py – add three routes
@admin_bp.route('/sessions', methods=['GET','POST'])
@admin_required
def manage_sessions():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if mongo.sessions.find_one({'name': name}):
            flash('Session exists', 'error')
        else:
            mongo.sessions.insert_one({'name': name, 'active': True})
            flash('Session added', 'success')
        return redirect(url_for('admin.manage_sessions'))
    items = list(mongo.sessions.find())
    return render_template('admin/sessions.html', items=items, title='Sessions')

# For terms
@admin_bp.route('/terms', methods=['GET','POST'])
@admin_required
def manage_terms():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if mongo.terms.find_one({'name': name}):
            flash('Term exists', 'error')
        else:
            mongo.terms.insert_one({'name': name, 'active': True})
            flash('Session added', 'success')
        return redirect(url_for('admin.manage_terms'))
    items = list(mongo.terms.find())
    return render_template('admin/terms.html', items=items, title='Terms')

# For classes
@admin_bp.route('/classes', methods=['GET','POST'])
@admin_required
def manage_classes():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if mongo.classes.find_one({'name': name}):
            flash('Class exists', 'error')
        else:
            mongo.classes.insert_one({'name': name, 'active': True})
            flash('Class added', 'success')
        return redirect(url_for('admin.manage_classes'))
    items = list(mongo.classes.find())
    return render_template('admin/classes.html', items=items, title='Classes')



@admin_bp.route('/upload-students', methods=['GET', 'POST'])
@admin_required
def upload_students():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'CSV file required'}), 400

        stream = StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_reader = csv.DictReader(stream)
        inserted = 0
        errors = []

        for i, row in enumerate(csv_reader, start=2):
            try:
                adm_no = row['admission_number'].strip()
                name = row['name'].strip()
                cls = row['class'].strip()

                if not all([adm_no, name, cls]):
                    errors.append(f"Row {i}: Missing data")
                    continue

                # Prevent duplicate admission numbers
                if mongo.db.students.find_one({'admission_number': adm_no}):
                    errors.append(f"Row {i}: Duplicate admission number {adm_no}")
                    continue

                mongo.students.insert_one({
                    'admission_number': adm_no,
                    'name': name,
                    'class': cls,
                    'created_at': datetime.utcnow()
                })
                inserted += 1
            except Exception as e:
                errors.append(f"Row {i}: {str(e)}")

        msg = f"Uploaded {inserted} students."
        if errors:
            msg += f" {len(errors)} errors."
        return jsonify({'status': 'success', 'message': msg, 'errors': errors}), 200

    return render_template('admin/upload_students.html')

@admin_bp.route('/subjects', methods=['GET', 'POST'])
@admin_required
def manage_subjects():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Subject name required', 'error')
        elif mongo.subjects.find_one({'name': {'$regex': f'^{name}$', '$options': 'i'}}):
            flash('Subject already exists', 'error')
        else:
            mongo.subjects.insert_one({'name': name, 'added_at': datetime.utcnow()})
            flash('Subject added', 'success')
        return redirect(url_for('admin.manage_subjects'))

    subjects = list(mongo.subjects.find().sort('name'))
    return render_template('admin/subjects.html', subjects=subjects)

@admin_bp.route('/api/subjects')
def get_subjects():
    subjects = list(mongo.subjects.find().sort('name'))
    return jsonify([{'name': s['name']} for s in subjects])

# Add to admin.py — Teacher Registration
@admin_bp.route('/teachers', methods=['GET', 'POST'])
@admin_required
def manage_teachers():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if len(password) < 6:
            flash('Password too short', 'error')
        elif mongo.users.find_one({'username': username}):
            flash('Username taken', 'error')
        else:
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            mongo.users.insert_one({
                'username': username,
                'password': hashed.decode('utf-8'),
                'role': 'teacher',
                'created_at': datetime.utcnow()
            })
            flash('Teacher added', 'success')
        return redirect(url_for('admin.manage_teachers'))

    teachers = list(mongo.users.find({'role': 'teacher'}))
    return render_template('admin/teachers.html', teachers=teachers)

# routes/admin.py
@admin_bp.route('/assign', methods=['GET', 'POST'])
@admin_required
def assign_teachers():
    teachers = list(mongo.users.find({'role': 'teacher'}, {'username': 1}))
    sessions = list(mongo.sessions.find({}, {'name': 1, '_id': 0}).sort('name'))
    classes  = list(mongo.classes.find({}, {'name': 1, '_id': 0}).sort('order'))
    subjects = list(mongo.subjects.find({}, {'name': 1, '_id': 0}).sort('name'))

    if request.method == 'POST':
        teacher_id = request.form['teacher_id']
        session_name = request.form['session']
        class_name = request.form['class']
        subject_name = request.form['subject']

        # Prevent duplicate
        existing = mongo.teacher_assignments.find_one({
            'teacher_id': ObjectId(teacher_id),
            'session': session_name,
            'class': class_name,
            'subject': subject_name
        })
        if existing:
            flash('Assignment already exists', 'error')
        else:
            mongo.teacher_assignments.insert_one({
                'teacher_id': ObjectId(teacher_id),
                'session': session_name,
                'class': class_name,
                'subject': subject_name,
                'assigned_at': datetime.utcnow()
            })
            flash('Assignment added', 'success')
        return redirect(url_for('admin.assign_teachers'))

    assignments = list(mongo.teacher_assignments.aggregate([
        {"$lookup": {"from": "users", "localField": "teacher_id", "foreignField": "_id", "as": "teacher"}},
        {"$unwind": "$teacher"},
        {"$project": {"teacher.username": 1, "session": 1, "class": 1, "subject": 1}}
    ]))

    return render_template(
        'admin/assign.html',
        teachers=teachers,
        sessions=sessions,
        classes=classes,
        subjects=subjects,
        assignments=assignments
    )