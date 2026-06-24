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

# Hardcoded grading system — easy to change
GRADE_SCALE = [
    (70, 100, 'A', 'Distinction'),
    (60, 69, 'B', 'Above Average'),
    (50, 59, 'C', 'Credit'),
    (40, 49, 'D', 'Below Average'),
    (0, 39, 'F', 'Failed')
]

# ==================== TEACHER LOGIN ====================
@teacher_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        phone_password = request.form['password'].strip()

        # Get the CURRENT active term
        current_term = get_current_context()['term']   # Make sure this returns the active term

        # Find teacher profile for the CURRENT term first
        teacher = mongo.teachers.find_one({
            'email': email,
            'phone': phone_password,
            'term': current_term
        })

        # If not found in current term, check any term (fallback)
        if not teacher:
            teacher = mongo.teachers.find_one({
                'email': email,
                'phone': phone_password
            })

        if teacher:
            sesh['teacher_email'] = teacher['email']
            sesh['teacher_name'] = teacher['name']
            sesh['teacher_session'] = teacher['session']
            sesh['teacher_term'] = teacher['term']
            sesh['role'] = 'teacher'

            flash(f'Logged in successfully for {teacher["term"]} Term', 'success')
            return redirect(url_for('teacher.dashboard'))

        flash('Invalid email or phone number', 'error')

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
    session_val = sesh.get('teacher_session')
    term = sesh.get('teacher_term')

    teacher_doc = mongo.teachers.find_one({
        'email': teacher_email,
        'session': session_val,
        'term': term
    })
    is_primary_teacher = teacher_doc.get('is_primary', False) if teacher_doc else False

    class_teacher_of = [a['class'] for a in mongo.class_assignments.find({
        'teacher_email': teacher_email,
        'session': session_val,
        'term': term
    })]

    assigned_subjects = list(mongo.subject_assignments.find({
        'teacher_email': teacher_email,
        'session': session_val,
        'term': term
    }))

    return render_template('teacher/dashboard.html',
                           teacher={'name': sesh.get('teacher_name'), 'term': term, 'session': session_val},
                           class_teacher_of=class_teacher_of,
                           assigned_subjects=assigned_subjects,
                           is_primary_teacher=is_primary_teacher)
    
    
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
    

    # Verify assignment
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

    # All students in class for this term
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    # Fetch current subject enrollment
    enrollment_doc = mongo.subject_enrollments.find_one({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    enrolled_student_ids = enrollment_doc['enrolled_admission_numbers'] if enrollment_doc else []
    # All results for this subject/class/term
    results_cursor = mongo.results.find({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    })

    # Fetch existing scores for pre-fill
    existing_scores = {}
    class_average = 0.0
    for r in results_cursor:
        adm_no = r['admission_number']
        existing_scores[adm_no] = r
        ca1 = min(max(float(request.form.get(f'ca1_{adm_no}', 0)), 0), 15)
        ca2 = min(max(float(request.form.get(f'ca2_{adm_no}', 0)), 0), 15)
        exam = min(max(float(request.form.get(f'exam_{adm_no}', 0)), 0), 70)
        if 'class_average' in r:
            class_average = r['class_average']

    # Bringing in the pevious totals from first and second terms if the active term is third term
    previous_totals = {}
    if term == 'Third':
        for prev_term in ['First', 'Second']:
            for r in mongo.results.find({
                'subject': subject,
                'class': class_name,
                'session': session_val,
                'term': prev_term,
                'admission_number': {'$in': enrolled_student_ids}
            }):
                adm_no = r['admission_number']
                if adm_no not in previous_totals:
                    previous_totals[adm_no] = {}
                previous_totals[adm_no][prev_term.lower()] = r.get('total', 0)
            

    return render_template(
        'teacher/subject_detail.html',
        subject=subject,
        class_name=class_name,
        students=students,
        enrolled_student_ids=enrolled_student_ids,
        existing_scores=existing_scores,
        class_average=class_average,
        term=term,
        session=session_val,
        previous_totals=previous_totals if term == 'Third' else None
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
    try:
        subject = request.form.get('subject')
        class_name = request.form.get('class')
        adm_no = request.form.get('adm_no')
        action = request.form.get('action')

        if not all([subject, class_name, adm_no, action]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        session_val = sesh['teacher_session']
        term = sesh['teacher_term']

        filter_query = {
            'subject': subject,
            'class': class_name,
            'session': session_val,
            'term': term
        }

        # Get or create enrollment document
        enrollment = mongo.subject_enrollments.find_one(filter_query)

        if not enrollment:
            enrollment = {**filter_query, 'enrolled_admission_numbers': []}
            mongo.subject_enrollments.insert_one(enrollment)

        enrolled = set(enrollment.get('enrolled_admission_numbers', []))

        if action == 'enroll':
            enrolled.add(adm_no)
            # Create default result if enrolling
            create_default_result(adm_no, subject, class_name, session_val, term)
        elif action == 'unenroll':
            enrolled.discard(adm_no)
            # Optional: delete result when unenrolling
            mongo.results.delete_one({
                'admission_number': adm_no,
                'subject': subject,
                'session': session_val,
                'term': term
            })

        # Save back
        mongo.subject_enrollments.update_one(
            filter_query,
            {'$set': {'enrolled_admission_numbers': list(enrolled)}}
        )

        return jsonify({'success': True})

    except Exception as e:
        print("Enroll Student Error:", str(e))
        return jsonify({'success': False, 'error': str(e)}), 500
        
"""

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
    """
    
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
@teacher_bp.route('/student/<regex:adm_no>')
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
    # Get all results for this subject/class/term
    results = list(mongo.results.find({
        'subject': subject,
        'class': class_name,
        'session': session_val,
        'term': term
    }))

    if not results:
        return

    # Calculate class average
    totals = [r.get('total', 0) for r in results]
    class_avg = round(sum(totals) / len(totals), 2) if totals else 0

    # Sort for positions (handle ties properly)
    sorted_results = sorted(results, key=lambda r: r.get('total', 0), reverse=True)
    
    current_pos = 1
    prev_total = None

    for i, result in enumerate(sorted_results):
        if i > 0 and result.get('total', 0) < prev_total:
            current_pos = i + 1
        
        mongo.results.update_one(
            {'_id': result['_id']},
            {'$set': {
                'position': current_pos,
                'class_average': class_avg
            }}
        )
        prev_total = result.get('total', 0)

"""
@teacher_bp.route('/save_subject_scores', methods=['POST'])
@teacher_required
def save_subject_scores():
    subject = request.form['subject']
    class_name = request.form['class']
    term = request.form['term']
    session_val = sesh['teacher_session']

    enrolled_adms = request.form.getlist('enrolled_students')

    # Update enrollment
    mongo.subject_enrollments.update_one(
        {'subject': subject, 'class': class_name, 'session': session_val, 'term': term},
        {'$set': {'enrolled_admission_numbers': enrolled_adms}},
        upsert=True
    )

    results_to_save = []

    for adm_no in enrolled_adms:
        ca1 = min(float(request.form.get(f'ca1_{adm_no}', 0)), 15)
        ca2 = min(float(request.form.get(f'ca2_{adm_no}', 0)), 15)
        exam = min(float(request.form.get(f'exam_{adm_no}', 0)), 70)

        total = ca1 + ca2 + exam
        if term == 'Third':
            cum1 = float(request.form.get(f'cum1_{adm_no}', 0))
            cum2 = float(request.form.get(f'cum2_{adm_no}', 0))
            total = round((cum1 + cum2 + total) / 3, 2)

        grade, remark = get_grade_and_remark(total)

        results_to_save.append({
            'admission_number': adm_no,
            'total': total,
            'grade': grade,
            'remark': remark
        })

        # Upsert individual result
        mongo.results.update_one(
            {'admission_number': adm_no, 'subject': subject, 'session': session_val, 'term': term, 'class':class_name},
            {'$set': {
                'ca1': ca1, 'ca2': ca2, 'exam': exam,
                'total': total, 'grade': grade, 'remark': remark,
                'date_updated': datetime.utcnow()
            }},
            upsert=True
        )

    # Calculate positions (handle ties)
    sorted_results = sorted(results_to_save, key=lambda x: x['total'], reverse=True)
    current_pos = 1
    prev_total = None
    for i, res in enumerate(sorted_results):
        if i > 0 and res['total'] < prev_total:
            current_pos = i + 1
        mongo.results.update_one(
            {'admission_number': res['admission_number'], 'subject': subject, 'session': session_val, 'term': term},
            {'$set': {'position': current_pos}}
        )
        prev_total = res['total']

    # Class average
    totals = [r['total'] for r in results_to_save]
    class_avg = round(sum(totals) / len(totals), 2) if totals else 0

    # Save average to all records
    mongo.results.update_many(
        {'subject': subject, 'class': class_name, 'session': session_val, 'term': term},
        {'$set': {'class_average': class_avg}}
    )

    flash('Scores saved successfully with grades, positions, and class average!', 'success')
    return redirect(url_for('teacher.subject_detail', subject=subject, class_name=class_name))

"""
@teacher_bp.route('/save_subject_scores', methods=['POST'])
@teacher_required
def save_subject_scores():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400

        subject = data.get('subject')
        class_name = data.get('class')
        term = data.get('term')
        session_val = sesh.get('teacher_session')
        scores_list = data.get('scores', [])  # New format from frontend

        if not all([subject, class_name, term, session_val]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        saved_count = 0

        for score_data in scores_list:
            adm_no = score_data.get('adm_no')
            ca1 = float(score_data.get('ca1', 0))
            ca2 = float(score_data.get('ca2', 0))
            exam = float(score_data.get('exam', 0))

            # Calculate total
            current_total = ca1 + ca2 + exam

            if term == 'Third':
                # Get cumulative from previous terms (more reliable)
                first = mongo.results.find_one({
                    'admission_number': adm_no,
                    'subject': subject,
                    'session': session_val,
                    'term': 'First'
                }) or {}
                second = mongo.results.find_one({
                    'admission_number': adm_no,
                    'subject': subject,
                    'session': session_val,
                    'term': 'Second'
                }) or {}

                cum1 = float(first.get('total', 0))
                cum2 = float(second.get('total', 0))
                final_total = round((cum1 + cum2 + current_total) / 3, 2)
            else:
                final_total = round(current_total, 2)

            grade, remark = get_grade_and_remark(final_total)

            # Upsert result
            mongo.results.update_one(
                {
                    'admission_number': adm_no,
                    'subject': subject,
                    'class': class_name,
                    'session': session_val,
                    'term': term
                },
                {'$set': {
                    'ca1': ca1,
                    'ca2': ca2,
                    'exam': exam,
                    'total': final_total,
                    'grade': grade,
                    'remark': remark,
                    'date_updated': datetime.utcnow()
                }},
                upsert=True
            )
            saved_count += 1

        # Update class average and positions
        update_class_average_and_positions(subject, class_name, session_val, term)

        return jsonify({
            'success': True,
            'message': f'Successfully saved scores for {saved_count} student(s)'
        })

    except Exception as e:
        print("Save Scores Error:", str(e))
        return jsonify({'success': False, 'error': str(e)}), 500

# ======================= Broad sheet ===============
def get_grade_and_remark(total):
    for min_score, max_score, grade, remark in GRADE_SCALE:
        if min_score <= total <= max_score:
            return grade, remark
    return 'F', 'Failed'  # fallback


@teacher_bp.route('/broadsheet/<class_name>')
@teacher_required
def teacher_broadsheet(class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    # Security: Ensure this teacher is assigned as class teacher for this class
    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not the class teacher for this class.', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Get all students in this class for the term
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    if not students:
        flash(f'No students enrolled in {class_name} for {term} Term.', 'info')
        return redirect(url_for('teacher.dashboard'))

    # Get all subjects that have results in this class/term
    subjects = sorted(mongo.results.distinct('subject', {
        'class': class_name,
        'session': session_val,
        'term': term
    }))

    return render_template(
        'teacher/broadsheet.html',
        class_name=class_name,
        term=term,
        current_session=session_val,
        students=students,
        subjects=subjects
    )

# The primary school
@teacher_bp.route('/primary_entry/<class_name>')
@teacher_required
def primary_entry(class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    # Security check
    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not authorized for this class.', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Get students
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    # Get subjects safely
    subjects = sorted(list(mongo.results.distinct('subject', {
        'class': class_name,
        'session': session_val,
        'term': term
    })))

    # Fallback subjects if none found yet
    if not subjects:
        subjects = ["Mathematics", "English", "Basic Science", "Social Studies", 
                   " Civic Education", "Home Economics", "Physical Education", 
                   "Art & Craft", "Computer Studies", "Christian Religious Knowledge"]

    return render_template('teacher/primary_entry.html',
                           class_name=class_name,
                           students=students,
                           subjects=subjects,           # All possible subjects
                           selected_subjects=subjects,  # Initially all selected
                           term=term,
                           session=session_val)

    
@teacher_bp.route('/save_primary_scores', methods=['POST'])
@teacher_required
def save_primary_scores():
    print("=== SAVE PRIMARY SCORES CALLED ===")
    
    try:
        data = request.get_json()
        if not data:
            print("❌ No JSON data received")
            return jsonify({'success': False, 'message': 'No data received'}), 400

        adm_no = data.get('admission_number')
        class_name = data.get('class_name')
        scores = data.get('scores', {})
        psychomotor = data.get('psychomotor', {})

        session_val = sesh.get('teacher_session')
        term = sesh.get('teacher_term')

        print(f"📌 Session: {session_val} | Term: {term} | Student: {adm_no}")
        print(f"📌 Scores keys: {list(scores.keys()) if scores else 'None'}")

        if not all([adm_no, class_name, session_val, term]):
            return jsonify({'success': False, 'message': 'Missing session data'}), 400

        if not scores:
            return jsonify({'success': False, 'message': 'No scores provided'}), 400

        saved_count = 0

        for subject, marks in scores.items():
            try:
                ca1 = float(marks.get('ca1') or 0)
                ca2 = float(marks.get('ca2') or 0)
                exam = float(marks.get('exam') or 0)
                current_total = ca1 + ca2 + exam
                final_total = round(current_total, 2)

                # Safe grade
                try:
                    grade, remark = get_grade_and_remark(final_total)
                except:
                    grade, remark = "P", "Pass"

                # === CRITICAL: Full diagnostic ===
                filter_query = {
                    'admission_number': adm_no,
                    'subject': subject,
                    'class': class_name,
                    'session': session_val,
                    'term': term
                }

                update_doc = {
                    '$set': {
                        'ca1': ca1,
                        'ca2': ca2,
                        'exam': exam,
                        'total': final_total,
                        'grade': grade,
                        'remark': remark,
                        'date_updated': datetime.utcnow()
                    }
                }

                result = mongo.results.update_one(filter_query, update_doc, upsert=True)
                
                print(f"✅ Update Result for {subject}:")
                print(f"   Matched: {result.matched_count}, Modified: {result.modified_count}, Upserted: {result.upserted_id}")

                saved_count += 1

            except Exception as e:
                print(f"⚠️ Error processing {subject}: {e}")

        # Psychomotor
        if psychomotor:
            try:
                mongo.student_term_profiles.update_one(
                    {'admission_number': adm_no, 'session': session_val, 'term': term},
                    {'$set': {'psychomotor': psychomotor, 'class': class_name, 'date_updated': datetime.utcnow()}},
                    upsert=True
                )
                print("✅ Psychomotor saved")
            except Exception as e:
                print(f"⚠️ Psychomotor error: {e}")

        print(f"🎉 Finished - Saved {saved_count} subjects")
        return jsonify({
            'success': True,
            'message': f'{saved_count} subject(s) saved successfully for {adm_no}',
            'saved_count': saved_count
        })

    except Exception as e:
        print("❌ CRITICAL ERROR:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Server error'}), 500
        
# ==================== PRIMARY SCHOOL TEACHER ROUTES ====================

@teacher_bp.route('/primary_class_students/<class_name>')
@teacher_required
def primary_class_students(class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    # Security check
    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not the class teacher for this class.', 'error')
        return redirect(url_for('teacher.dashboard'))

    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    return render_template('teacher/primary_class_students.html',
                           class_name=class_name,
                           students=students)


@teacher_bp.route('/primary_student_entry/<class_name>/<regex(".*"):adm_no>')
@teacher_required
def primary_student_entry(class_name, adm_no):
    teacher_email = sesh['teacher_email']
    session_val = sesh.get('teacher_session')
    term = sesh.get('teacher_term')

    # Security Check
    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('Access denied.', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Get student details
    student_data = mongo.students.find_one({'admission_number': adm_no})
    if not student_data:
        flash('Student not found.', 'error')
        return redirect(url_for('teacher.primary_class_students', class_name=class_name))
    
    # Verify enrollment
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': session_val,
        'term': term,
        'class': class_name
    })
    if not enrollment:
        flash('Student not enrolled in this class/term.', 'error')
        return redirect(url_for('teacher.primary_class_students', class_name=class_name))

    # Get Subjects
    class_subjects_doc = mongo.primary_class_subjects.find_one({'class_name': class_name})
    subjects = class_subjects_doc.get('subjects', []) if class_subjects_doc else ["Mathematics", "English", "Basic Science"]

    psychomotor_skills = ["Punctuality", "Neatness", "Honesty", "Leadership", "Politeness", "Teamwork", "Initiative", "Reliability"]

    # FIX: Fetch from the CORRECT collection - 'results' not 'primary_results'
    existing_scores = {}
    for subject in subjects:
        result = mongo.results.find_one({
            'admission_number': adm_no,
            'subject': subject,
            'class': class_name,
            'session': session_val,
            'term': term
        })
        if result:
            existing_scores[subject] = {
                'ca1': result.get('ca1', 0),
                'ca2': result.get('ca2', 0),
                'exam': result.get('exam', 0)
            }
    
    # Fetch psychomotor from student_term_profiles
    profile = mongo.student_term_profiles.find_one({
        'admission_number': adm_no,
        'session': session_val,
        'term': term
    })
    existing_psychomotor = profile.get('psychomotor', {}) if profile else {}

    return render_template('teacher/primary_student_entry.html',
                           student=student_data,
                           class_name=class_name,
                           subjects=subjects,
                           psychomotor_skills=psychomotor_skills,
                           term=term,
                           session=session_val,
                           existing_scores=existing_scores,
                           existing_psychomotor=existing_psychomotor)



@teacher_bp.route('/primary_broadsheet/<class_name>')
@teacher_required
def primary_teacher_broadsheet(class_name):
    teacher_email = sesh['teacher_email']
    session_val = sesh['teacher_session']
    term = sesh['teacher_term']

    # Security: Ensure this teacher is assigned as class teacher for this class
    assignment = mongo.class_assignments.find_one({
        'teacher_email': teacher_email,
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if not assignment:
        flash('You are not the class teacher for this class.', 'error')
        return redirect(url_for('teacher.dashboard'))

    # Get all students in this class for the term
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_val,
        'term': term
    }).sort('name', 1))

    if not students:
        flash(f'No students enrolled in {class_name} for {term} Term.', 'info')
        return redirect(url_for('teacher.dashboard'))

    # Get subjects for this primary class (from class configuration)
    class_subjects_doc = mongo.primary_class_subjects.find_one({'class_name': class_name})
    if not class_subjects_doc or not class_subjects_doc.get('subjects'):
        flash(f'No subjects configured for {class_name}. Please contact administrator.', 'error')
        return redirect(url_for('teacher.dashboard'))
    
    subjects = class_subjects_doc.get('subjects', [])

    # Fetch all results for these students in one go (efficient aggregation)
    admission_numbers = [s['admission_number'] for s in students]
    
    # Get all results for these students
    all_results = list(mongo.results.find({
        'admission_number': {'$in': admission_numbers},
        'class': class_name,
        'session': session_val,
        'term': term
    }))
    
    # Organize results by student and subject
    results_by_student = {}
    for result in all_results:
        adm_no = result['admission_number']
        subject = result['subject']
        if adm_no not in results_by_student:
            results_by_student[adm_no] = {}
        results_by_student[adm_no][subject] = {
            'ca1': result.get('ca1', 0),
            'ca2': result.get('ca2', 0),
            'exam': result.get('exam', 0),
            'total': result.get('total', 0),
            'grade': result.get('grade', 'F'),
            'remark': result.get('remark', '')
        }
    
    # Get psychomotor skills for all students
    all_profiles = list(mongo.student_term_profiles.find({
        'admission_number': {'$in': admission_numbers},
        'session': session_val,
        'term': term
    }))
    
    psychomotor_by_student = {}
    for profile in all_profiles:
        adm_no = profile['admission_number']
        psychomotor_by_student[adm_no] = profile.get('psychomotor', {})
    
    # Calculate overall performance for each student
    student_performance = []
    for student in students:
        adm_no = student['admission_number']
        student_results = results_by_student.get(adm_no, {})
        
        # Calculate subject totals and average
        subject_totals = []
        for subject in subjects:
            if subject in student_results:
                total = student_results[subject].get('total', 0)
                subject_totals.append(total)
        
        if subject_totals:
            total_score = sum(subject_totals)
            average = round(total_score / len(subject_totals), 2)
            
            # Calculate overall grade based on average
            if average >= 75:
                overall_grade = 'A'
                overall_remark = 'Excellent'
            elif average >= 65:
                overall_grade = 'B'
                overall_remark = 'Very Good'
            elif average >= 55:
                overall_grade = 'C'
                overall_remark = 'Good'
            elif average >= 45:
                overall_grade = 'D'
                overall_remark = 'Average'
            elif average >= 40:
                overall_grade = 'E'
                overall_remark = 'Pass'
            else:
                overall_grade = 'F'
                overall_remark = 'Fail'
        else:
            total_score = 0
            average = 0
            overall_grade = 'N/A'
            overall_remark = 'No Results'
        
        student_performance.append({
            'student': student,
            'results': student_results,
            'psychomotor': psychomotor_by_student.get(adm_no, {}),
            'total_score': total_score,
            'average': average,
            'overall_grade': overall_grade,
            'overall_remark': overall_remark
        })
    
    # Sort by total score (descending) for position
    student_performance.sort(key=lambda x: x['total_score'], reverse=True)
    
    # Assign positions
    for idx, perf in enumerate(student_performance, 1):
        perf['position'] = idx
    
    # Sort back by student name for display
    student_performance.sort(key=lambda x: x['student'].get('name', ''))
    
    # Get class teacher's comment (from term profile - can be added later)
    class_comment = ""
    class_profile = mongo.class_term_profiles.find_one({
        'class': class_name,
        'session': session_val,
        'term': term
    })
    if class_profile:
        class_comment = class_profile.get('teacher_comment', '')

    return render_template(
        'teacher/primary_broadsheet.html',
        class_name=class_name,
        term=term,
        current_session=session_val,
        subjects=subjects,
        student_performance=student_performance,
        class_comment=class_comment,
        psychomotor_skills=["Punctuality", "Neatness", "Honesty", "Leadership", "Politeness", "Teamwork", "Initiative", "Reliability"]
    )