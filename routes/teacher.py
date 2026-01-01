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
        email = request.form['email'].strip().lower()
        phone_password = request.form['password'].strip()  # Phone number as password

        teacher = mongo.teachers.find_one({'email': email})

        if teacher and teacher['phone'] == phone_password:
            sesh['teacher_email'] = teacher['email']
            sesh['teacher_name'] = teacher['name']
            sesh['teacher_session'] = teacher['session']
            sesh['teacher_term'] = teacher['term']
            sesh['role'] = 'teacher'
            return redirect(url_for('teacher.dashboard'))

        flash('Invalid email or phone number (password)', 'error')

    return render_template('teacher/login.html')

# ==================== LOGOUT ====================
@teacher_bp.route('/logout')
def logout():
    sesh.clear()
    return redirect(url_for('teacher.login'))
# ==================== DASHBOARD ====================
# routes/teacher.py

@teacher_bp.route('/dashboard')
@teacher_required
def dashboard():
    teacher_email = sesh['teacher_email']
    teacher_session = sesh['teacher_session']
    teacher_term = sesh['teacher_term']

    # Fetch teacher profile
    teacher = mongo.teachers.find_one({
        'email': teacher_email,
        'session': teacher_session,
        'term': teacher_term
    })

    if not teacher:
        flash('Teacher profile not found for current term.', 'error')
        return redirect(url_for('teacher.logout'))

    # Fetch subject assignments
    subject_assignments = list(mongo.subject_assignments.find({
        'teacher_email': teacher_email,
        'session': teacher_session,
        'term': teacher_term
    }))

    assigned_subjects_count = len(subject_assignments)
    assigned_subjects = list(mongo.subject_assignments.find({
    'teacher_email': teacher_email,
    'session': teacher_session,
    'term': teacher_term
}).sort('subject', 1))

    # Fetch class teacher assignment
    class_assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'session': teacher_session,
        'term': teacher_term
    })
    class_teacher_of = class_assignment['class'] if class_assignment else None

    # Optional: Pass full lists if you want to display them
    return render_template(
        'teacher/dashboard.html',
        teacher=teacher,
        assigned_subjects_count=assigned_subjects_count,
        assigned_subjects=subject_assignments,  # List of dicts for display
        class_teacher_of=class_teacher_of
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

    # New Route: Subject Detail Page (List Students, Enroll, Enter Scores)
@teacher_bp.route('/subject/<subject>/<class_name>')
@teacher_required
def subject_detail(subject, class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    teacher = mongo.teachers.find_one({'email': teacher_email})
    # Verify teacher is assigned to this subject/class
    assignment = mongo.subject_assignments.find_one({
        'teacher_email': teacher_email,
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not assigned to this subject or class', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Fetch all students in this class (from admin enrollment — assume students have 'class', 'session')
    # Replace the students query with:
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    # Fetch or create enrollment doc
    enrollment_doc = mongo.subject_enrollments.find_one({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not enrollment_doc:
        enrollment_doc = {
            'subject': subject,
            'class': class_name,
            'session': session_val,
            'term': term,
            'enrolled_students': [],
            'date_updated': datetime.utcnow()
        }
        mongo.subject_enrollments.insert_one(enrollment_doc)

    enrolled = set(enrollment_doc['enrolled_students'])

    # Fetch existing scores for enrolled students (for display/edit)
    scores = {}
    for student in students:
        adm_no = student['admission_number']
        if adm_no in enrolled:
            result = mongo.results.find_one({
                'admission_number': adm_no,
                'subject': subject,
                'session': session_val,
                'term': term
            })
            if not result:
                result = create_default_result(adm_no, subject, class_name, session_val, term)  # Function below
            scores[adm_no] = result
    # Fetch existing scores for pre-fill
    existing_scores = {}
    results = list(mongo.results.find({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    }))
    for r in results:
        existing_scores[r['admission_number']] = r
    
    return render_template(
        'teacher/subject_detail.html',
        subject=subject,
        class_name=class_name,
        students=students,
        enrolled=enrolled,
        scores=scores,
        term=term,
        teacher=teacher,
        session=session_val,
        existing_scores=existing_scores,
        enrolled_student_ids=enrolled
    )

# Helper Function: Create Default Result Doc (with auto-pull for Third Term)
def create_default_result(adm_no, subject, class_name, session_val, term):
    result = {
        'admission_number': adm_no,
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term,
        'ca1': 0,
        'ca2': 0,
        'exam': 0,
        'total': 0,
        'position': None,
        'class_average': None,
        'date_updated': datetime.utcnow()
    }

    if term == 'Third':
        # Auto-pull First Term
        first = mongo.results.find_one({
            'admission_number': adm_no,
            'subject': subject,
            'session': session_val,
            'term': 'First'
        })
        result['cumulative1'] = first['total'] if first else 0

        # Auto-pull Second Term
        second = mongo.results.find_one({
            'admission_number': adm_no,
            'subject': subject,
            'session': session_val,
            'term': 'Second'
        })
        result['cumulative2'] = second['total'] if second else 0

    mongo.results.insert_one(result)
    return result

# AJAX Route: Enroll/Unenroll Student
@teacher_bp.route('/enroll_student', methods=['POST'])
@teacher_required
def enroll_student():
    subject = request.form['subject']
    class_name = request.form['class']
    adm_no = request.form['adm_no']
    action = request.form['action']  # 'enroll' or 'unenroll'
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    enrollment = mongo.subject_enrollments.find_one({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })

    if enrollment:
        enrolled = set(enrollment['enrolled_students'])

        if action == 'enroll':
            if adm_no not in enrolled:
                enrolled.add(adm_no)
                # Create default result
                create_default_result(adm_no, subject, class_name, session_val, term)
        elif action == 'unenroll':
            if adm_no in enrolled:
                enrolled.remove(adm_no)
                # Optional: Delete result? Or keep for history
                mongo.results.delete_one({
                    'admission_number': adm_no,
                    'subject': subject,
                    'session': session_val,
                    'term': term
                })

        mongo.subject_enrollments.update_one(
            {'_id': enrollment['_id']},
            {'$set': {'enrolled_students': list(enrolled)}}
        )

        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Enrollment not found'}), 400

# AJAX Route: Save Scores & Auto-Calculate
@teacher_bp.route('/save_scores', methods=['POST'])
@teacher_required
def save_scores():
    adm_no = request.form['adm_no']
    subject = request.form['subject']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    # Fetch result doc
    result = mongo.results.find_one({
        'admission_number': adm_no,
        'subject': subject,
        'session': session_val,
        'term': term
    })

    if result:
        # Update scores
        ca1 = float(request.form.get('ca1', 0))
        ca2 = float(request.form.get('ca2', 0))
        exam = float(request.form.get('exam', 0))

        total = ca1 + ca2 + exam
        if term == 'Third':
            cum1 = float(result.get('cumulative1', 0))
            cum2 = float(result.get('cumulative2', 0))
            total = round((cum1 + cum2 + total) / 3, 2)

        # Save updated result
        mongo.results.update_one(
            {'_id': result['_id']},
            {'$set': {
                'ca1': ca1,
                'ca2': ca2,
                'exam': exam,
                'total': total,
                'date_updated': datetime.utcnow()
            }}
        )

        # Auto-calc class average and positions for the subject
        update_class_average_and_positions(subject, result['class'], session_val, term)

        return jsonify({'success': True, 'total': total})

    return jsonify({'success': False, 'error': 'Result not found'}), 400
    
# Class Detail — List Students (Clickable Names)
@teacher_bp.route('/class/<class_name>')
@teacher_required
def class_detail(class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not the class teacher', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Students enrolled in this class for this term
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    return render_template(
        'teacher/class_students.html',
        class_name=class_name,
        students=students,
        term=term,
        session=session_val
    )

# Student Profile Page — Comment & Psychomotor Ratings
@teacher_bp.route('/student/<adm_no>')
@teacher_required
def student_profile(adm_no):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    student = mongo.students.find_one({'admission_number': adm_no})
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Verify teacher is class teacher of this student's class
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': session_val,
        'term': term
    })
    if not enrollment:
        flash('Student not enrolled in current term', 'error')
        return redirect(url_for('teacher.dashboard'))

    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': enrollment['class'],
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not the class teacher of this student', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Fetch or create profile
    profile = mongo.student_term_profiles.find_one({
        'admission_number': adm_no,
        'session': session_val,
        'term': term
    }) or {}

    results = list(mongo.results.find({
        'admission_number': adm_no,
        'session': session_val,
        'term': term
    }).sort('subject', 1))

    # Fetch profile for comment/ratings
    profile = mongo.student_term_profiles.find_one({
        'admission_number': adm_no,
        'session': session_val,
        'term': term
    }) or {}

    psychomotor_fields = [
        'punctuality', 'neatness', 'honesty', 'leadership',
        'politeness', 'teamwork', 'initiative', 'reliability'
    ]


    return render_template(
        'teacher/student_profile.html',
        student=student,
        results=results,
        profile=profile,
        psychomotor_fields=psychomotor_fields,
        class_name=enrollment['class'],
        term=term,
        session=session_val
    )

# Save Comment & Ratings
@teacher_bp.route('/save_profile', methods=['POST'])
@teacher_required
def save_profile():
    adm_no = request.form['adm_no']
    comment = request.form['comment'].strip()
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    ratings = {}
    for field in ['punctuality', 'neatness', 'honesty', 'leadership', 'politeness', 'teamwork', 'initiative', 'reliability']:
        val = request.form.get(field)
        if val:
            ratings[field] = int(val)

    mongo.student_term_profiles.update_one(
        {
            'admission_number': adm_no,
            'session': session_val,
            'term': term
        },
        {'$set': {
            'class_teacher_comment': comment,
            'psychomotor': ratings,
            'date_updated': datetime.utcnow()
        }},
        upsert=True
    )

    flash('Student profile updated successfully!', 'success')
    return redirect(url_for('teacher.student_profile', adm_no=adm_no))
    
# Helper: Update Average & Positions for All Enrolled in Subject
def update_class_average_and_positions(subject, class_name, session_val, term):
    enrollment = mongo.subject_enrollments.find_one({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })

    if enrollment:
        enrolled = enrollment['enrolled_students']
        results = list(mongo.results.find({
            'admission_number': {'$in': enrolled},
            'subject': subject,
            'session': session_val,
            'term': term
        }))

        totals = [r['total'] for r in results]
        class_avg = round(sum(totals) / len(totals), 2) if totals else 0

        # Sort for positions (descending total)
        sorted_results = sorted(results, key=lambda r: r['total'], reverse=True)
        for pos, r in enumerate(sorted_results, 1):
            mongo.results.update_one(
                {'_id': r['_id']},
                {'$set': {
                    'class_average': class_avg,
                    'position': pos
                }}
            )


@teacher_bp.route('/save_subject_scores', methods=['POST'])
@teacher_required
def save_subject_scores():
    subject = request.form['subject']
    class_name = request.form['class']
    term = request.form['term']
    session_val = sesh['teacher_session']

    # Get selected (enrolled) students
    enrolled_adms = request.form.getlist('enrolled_students')

    # Update subject enrollment (overwrite — prevents duplicates)
    mongo.subject_enrollments.update_one(
        {
            'subject': subject,
            'class': class_name,
            'session': session_val,
            'term': term
        },
        {'$set': {
            'enrolled_admission_numbers': enrolled_adms,
            'date_updated': datetime.utcnow()
        }},
        upsert=True
    )

    saved_count = 0
    for adm_no in enrolled_adms:
        ca1 = float(request.form.get(f'ca1_{adm_no}', 0))
        ca2 = float(request.form.get(f'ca2_{adm_no}', 0))
        exam = float(request.form.get(f'exam_{adm_no}', 0))

        total = ca1 + ca2 + exam
        if term == 'Third':
            cum1 = float(request.form.get(f'cum1_{adm_no}', 0))
            cum2 = float(request.form.get(f'cum2_{adm_no}', 0))
            total = round((cum1 + cum2 + total) / 3, 2)

        # Upsert — updates if exists, creates if not (prevents duplicates)
        result = mongo.results.update_one(
            {
                'admission_number': adm_no,
                'subject': subject,
                'session': session_val,
                'term': term
            },
            {'$set': {
                'ca1': ca1,
                'ca2': ca2,
                'exam': exam,
                'total': total,
                'date_updated': datetime.utcnow()
            }},
            upsert=True
        )

        if result.modified_count or result.upserted_id:
            saved_count += 1

    # Recalculate class stats
    update_class_average_and_positions(subject, class_name, session_val, term)

    flash(f'Successfully saved/updated scores for {saved_count} students!', 'success')
    return redirect(url_for('teacher.subject_detail', subject=subject, class_name=class_name))