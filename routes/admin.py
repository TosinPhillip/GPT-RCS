# routes/admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from extensions import mongo
from utils.auth import admin_required
from utils.sessions import get_current_context, get_active_enrollments, find_student_by_admission, get_active_session
from bson import ObjectId
from werkzeug.utils import secure_filename
import bcrypt
import os
import csv
from io import StringIO
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Hardcoded admin (consider moving to DB later)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = bcrypt.hashpw("gptschool2025".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'xlsx', 'csv'}

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Global class list (can be moved to collection later)
classes = ['JSS1', 'JSS2', 'JSS3', 'SSS1', 'SSS2', 'SSS3']


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        if username == ADMIN_USERNAME and bcrypt.checkpw(password, ADMIN_PASSWORD_HASH.encode('utf-8')):
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('student.search'))


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    return render_template('admin/dashboard.html')


# ==================== SESSIONS MANAGEMENT ====================
@admin_bp.route('/sessions')
@admin_required
def sessions_list():
    sessions = list(mongo.sessions.find().sort("name", -1))
    return render_template('admin/sessions.html', sessions=sessions)


@admin_bp.route('/sessions/create', methods=['GET', 'POST'])
@admin_required
def create_session():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if mongo.sessions.find_one({"name": name}):
            flash('Session already exists', 'error')
        else:
            mongo.sessions.insert_one({
                "name": name,
                "active": False,
                "terms": [
                    {"name": "First", "active": False},
                    {"name": "Second", "active": False},
                    {"name": "Third", "active": False}
                ]
            })
            flash(f'Session {name} created', 'success')
            return redirect(url_for('admin.sessions_list'))
    return render_template('admin/create_session.html')


@admin_bp.route('/sessions/<session_id>/activate', methods=['POST'])
@admin_required
def activate_session(session_id):
    mongo.sessions.update_many({}, {"$set": {"active": False}})
    mongo.sessions.update_one({"_id": ObjectId(session_id)}, {"$set": {"active": True}})
    flash('Session activated', 'success')
    return redirect(url_for('admin.sessions_list'))


@admin_bp.route('/sessions/<session_id>/term/<term_name>/activate', methods=['POST'])
@admin_required
def activate_term(session_id, term_name):
    # Global rule: only ONE active term across ALL sessions
    mongo.sessions.update_many({}, {"$set": {"terms.$[].active": False}})
    mongo.sessions.update_one(
        {"_id": ObjectId(session_id), "terms.name": term_name},
        {"$set": {"terms.$.active": True}}
    )
    flash(f'{term_name} Term activated globally', 'success')
    return redirect(url_for('admin.sessions_list'))


# ==================== STUDENT ENROLLMENT (SESSION-SPECIFIC) ====================
@admin_bp.route('/enroll-students')
@admin_required
def enroll_students():
    ctx = get_current_context()
    current_enrollments = get_active_enrollments()
    return render_template(
        'admin/term_enrollment.html',
        current_enrollments=current_enrollments,
        ctx=ctx,
        classes=classes  # Pass for dropdown
    )


@admin_bp.route('/enroll-students/add', methods=['POST'])
@admin_required
def add_student_enrollment():
    ctx = get_current_context()
    adm_no = request.form['admission_number'].strip().upper()
    class_ = request.form['class_']
    subjects = request.form.getlist('subjects')
    student_name = request.form.get('student_name', '').strip()

    if not adm_no or not class_:
        flash('Admission number and class are required', 'error')
        return redirect(url_for('admin.enroll_students'))

    # Find or create core student
    student = find_student_by_admission(adm_no)
    if not student:
        if not student_name:
            flash('Student name required for new student', 'error')
            return redirect(url_for('admin.enroll_students'))
        student_id = mongo.students.insert_one({
            "admission_number": adm_no,
            "name": student_name,
            "results_visible": True,
            "created_at": datetime.utcnow()
        }).inserted_id
        flash(f'New student {student_name} created', 'success')
    else:
        student_id = student['_id']
        flash(f'Existing student {student["name"]} enrolled', 'success')

    # Prevent duplicate enrollment in current term
    existing = mongo.enrollments.find_one({
        "student_id": student_id,
        "session": ctx["session_name"],
        "term": ctx["term"]
    })
    if existing:
        flash('Student already enrolled this term', 'warning')
    else:
        mongo.enrollments.insert_one({
            "student_id": student_id,
            "session": ctx["session_name"],
            "term": ctx["term"],
            "class_": class_,
            "subjects": subjects,
            "status": "active",
            "enrolled_at": datetime.utcnow()
        })
        flash(f'Enrolled in {class_}', 'success')

    return redirect(url_for('admin.enroll_students'))


# ==================== LEGACY ROUTES (kept for compatibility or future use) ====================
# You can gradually migrate these to use session context
@admin_bp.route('/students')
@admin_required
def manage_students():
    search = request.args.get('search', '').strip()
    query = {}
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'admission_number': {'$regex': search, '$options': 'i'}}
        ]
    students = list(mongo.students.find(query).sort('name', 1))
    sessions = list(mongo.sessions.find({}, {'name': 1}).sort('name', -1))
    return render_template('admin/students.html', students=students, sessions=sessions, classes=classes, search=search)


@admin_bp.route('/student/<student_id>', methods=['GET', 'POST'])
@admin_required
def student_detail(student_id):
    student = mongo.students.find_one({'_id': ObjectId(student_id)})
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('admin.manage_students'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'toggle_visibility':
            new_vis = not student.get('results_visible', True)
            mongo.students.update_one({'_id': ObjectId(student_id)}, {'$set': {'results_visible': new_vis}})
            flash(f'Results visibility {"blocked" if not new_vis else "allowed"}', 'success')
        elif action == 'promote':
            new_class = request.form.get('new_class')
            if new_class:
                mongo.students.update_one({'_id': ObjectId(student_id)}, {'$set': {'class_': new_class}})
                flash(f'Promoted to {new_class}', 'success')
        return redirect(url_for('admin.student_detail', student_id=student_id))

    results = list(mongo.results.find({'student_id': ObjectId(student_id)}).sort([('session', -1), ('term', 1)]))
    grouped_results = {}
    for res in results:
        key = (res.get('session', 'Unknown'), res.get('term', 'Unknown'))
        grouped_results.setdefault(key, []).append(res)

    return render_template('admin/student_detail.html', student=student, grouped_results=grouped_results, classes=classes)


@admin_bp.route('/toggle_visibility', methods=['POST'])
@admin_required
def toggle_visibility():
    adm_no = request.form['adm_no']
    current_visible = request.form.get('current_visible') == 'true'

    # Update in term_enrollments (your current term enrollment collection)
    result = mongo.term_enrollments.update_one(
        {'admission_number': adm_no},
        {'$set': {'results_visible': not current_visible}}
    )

    if result.modified_count:
        new_state = not current_visible
    else:
        # If not found, set to True by default
        mongo.term_enrollments.update_one(
            {'admission_number': adm_no},
            {'$set': {'results_visible': True}},
            upsert=True
        )
        new_state = True

    return jsonify({
        'success': True,
        'new_visible': new_state,
        'label': 'Visible' if new_state else 'Hidden'
    })


@admin_bp.route('/promote', methods=['GET', 'POST'])
@admin_required
def promote_students():
    ctx = get_current_context()
    next_session_name = request.args.get('next_session')

    all_sessions = list(mongo.sessions.find().sort("name", 1))
    current_session = ctx['session_name']

    # Auto-suggest next session
    if not next_session_name and all_sessions:
        current_idx = next((i for i, s in enumerate(all_sessions) if s['name'] == current_session), -1)
        if current_idx < len(all_sessions) - 1:
            next_session_name = all_sessions[current_idx + 1]['name']

    # Get current active enrollments
    current_enrollments = list(mongo.enrollments.find({
        "session": current_session,
        "status": "active"
    }))

    # Pre-enrich with student core data
    enriched_groups = {}
    for e in current_enrollments:
        student = mongo.students.find_one({"_id": e["student_id"]})
        student_data = {
            "enrollment_id": e["_id"],
            "class_": e["class_"],
            "name": student["name"] if student else "Unknown",
            "admission_number": student["admission_number"] if student else "N/A"
        }
        enriched_groups.setdefault(e["class_"], []).append(student_data)

    if request.method == 'POST':
        next_session = request.form['next_session']
        if not mongo.sessions.find_one({"name": next_session}):
            flash('Next session does not exist — create it first', 'error')
            return redirect(url_for('admin.promote_students'))

        promoted_count = 0
        promotion_map = {
            'Nursery 2': 'Primary 1',
            'Primary 6': 'JSS1',
            'JSS1': 'JSS2',
            'JSS2': 'JSS3',
            'JSS3': 'SSS1',
            'SSS1': 'SSS2',
            'SSS2':'SSS3',
            'SSS3': 'Graduated'
        }

        for enrollment_id in request.form.getlist('promote'):
            enrollment = mongo.enrollments.find_one({"_id": ObjectId(enrollment_id)})
            if not enrollment:
                continue

            current_class = enrollment['class_']
            new_class = promotion_map.get(current_class)

            if current_class == 'SSS3':
                mongo.enrollments.update_one(
                    {"_id": ObjectId(enrollment_id)},
                    {"$set": {"status": "alumni"}}
                )
                promoted_count += 1
                continue

            if not new_class:
                continue

            mongo.enrollments.insert_one({
                "student_id": enrollment["student_id"],
                "session": next_session,
                "term": get_current_context()['term'],
                "class_": new_class,
                "subjects": enrollment.get("subjects", []),
                "status": "active",
                "promoted_from": current_class,
                "promoted_at": datetime.utcnow()
            })
            promoted_count += 1

        flash(f'{promoted_count} students promoted to {next_session}', 'success')
        return redirect(url_for('admin.promote_students'))

    return render_template(
        'admin/promote.html',
        class_groups=enriched_groups,  # Pre-enriched
        current_session=current_session,
        next_session_name=next_session_name,
        all_sessions=all_sessions
    )


@admin_bp.route('/students/register', methods=['GET', 'POST'])
@admin_required
def register_students():
    if request.method == 'POST':
        action = request.form.get('action')

        # ===================== SINGLE STUDENT =====================
        if action == 'single':
            try:
                adm_no = request.form['admission_number'].strip()
                if mongo.students.find_one({'admission_number': adm_no}):
                    flash('Admission number already exists', 'danger')
                    return redirect(url_for('admin.register_students'))

                dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()

                student_data = {
                    'name': request.form['name'].strip().title(),
                    'class': request.form['class'].strip().upper(),
                    'gender': request.form['gender'].strip().title(),
                    'admission_number': adm_no,
                    'date_of_birth': dob,
                    'password': hash_password(request.form['password'].strip()),
                    'results_visible': request.form.get('results_visible') == 'on',
                    'date_registered': datetime.utcnow()
                }

                mongo.students.insert_one(student_data)
                flash(f'Student "{student_data["name"]}" registered successfully!', 'success')

            except ValueError:
                flash('Invalid date format', 'danger')
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')

            return redirect(url_for('admin.register_students'))

        # ===================== BULK CSV UPLOAD =====================
        elif action == 'bulk':
            if 'file' not in request.files:
                flash('No file selected', 'danger')
                return redirect(url_for('admin.register_students'))

            file = request.files['file']
            if file.filename == '':
                flash('No file selected', 'danger')
                return redirect(url_for('admin.register_students'))

            if not file.filename.lower().endswith('.csv'):
                flash('Only CSV files are allowed', 'danger')
                return redirect(url_for('admin.register_students'))

            try:
                # Read entire content safely
                raw_content = file.read().decode('utf-8-sig')
                if not raw_content.strip():
                    flash('Uploaded CSV file is empty', 'danger')
                    return redirect(url_for('admin.register_students'))

                stream = StringIO(raw_content)
                reader = csv.DictReader(stream)

                if reader.fieldnames is None:
                    flash('Invalid CSV format – no headers found', 'danger')
                    return redirect(url_for('admin.register_students'))

                # Normalize header names
                headers = [h.strip() for h in reader.fieldnames]
                required = ['name', 'class', 'gender', 'admission_number', 'date_of_birth', 'password']
                missing = [col for col in required if col not in headers]
                if missing:
                    flash(f'Missing required columns: {", ".join(missing)}', 'danger')
                    return redirect(url_for('admin.register_students'))

                success_count = 0
                errors = []
                row_number = 1  # Start after header

                for row in reader:
                    row_number += 1
                    try:
                        # Safe access with stripped keys
                        get_val = lambda key: row.get(key.strip(), '').strip() if row else ''

                        adm_no = get_val('admission_number')
                        if not adm_no:
                            errors.append(f"Row {row_number}: Admission number missing")
                            continue
                        if mongo.students.find_one({'admission_number': adm_no}):
                            errors.append(f"Row {row_number}: Admission {adm_no} already exists")
                            continue

                        name = get_val('name')
                        if not name:
                            errors.append(f"Row {row_number}: Name missing")
                            continue

                        password = get_val('password')
                        if not password:
                            errors.append(f"Row {row_number}: Password missing")
                            continue

                        dob_str = get_val('date_of_birth')
                        try:
                            dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                        except ValueError:
                            errors.append(f"Row {row_number}: Invalid date '{dob_str}' (use YYYY-MM-DD)")
                            continue

                        student_data = {
                            'name': name.title(),
                            'class': get_val('class').upper(),
                            'gender': get_val('gender').title(),
                            'admission_number': adm_no,
                            'date_of_birth': dob,
                            'password': hash_password(password),
                            'results_visible': get_val('results_visible').upper() in ['TRUE', '1', 'YES', 'ON', 'Y'],
                            'date_registered': datetime.utcnow()
                        }

                        mongo.students.insert_one(student_data)
                        success_count += 1

                    except Exception as e:
                        errors.append(f"Row {row_number}: {str(e)}")

                # === Final Flash Messages ===
                if success_count:
                    flash(f'✅ Successfully registered {success_count} student(s)!', 'success')

                if errors:
                    error_msg = f'⚠️ {len(errors)} row(s) failed:<br>' + '<br>'.join(errors[:12])
                    flash(error_msg, 'warning')

                if not success_count and not errors:
                    flash('No valid student records found in CSV', 'warning')

            except UnicodeDecodeError:
                flash('File must be saved as UTF-8 CSV', 'danger')
            except csv.Error as e:
                flash(f'CSV parsing error: {str(e)}', 'danger')
            except Exception as e:
                flash(f'Unexpected error processing file: {str(e)}', 'danger')

            return redirect(url_for('admin.register_students'))

    # GET — show registration page
    return render_template('admin/register_students.html')


@admin_bp.route('/teachers/create', methods=['GET', 'POST'])
@admin_required
def create_teacher():
    if request.method == 'POST':
        name = request.form['name'].strip().title()
        email = request.form['email'].strip().lower()
        phone = request.form['phone'].strip()
        session_val = request.form['session']
        term = request.form['term']

        # Validation
        if not all([name, email, phone, session_val, term]):
            flash('All fields are required', 'danger')
            return redirect(url_for('admin.create_teacher'))

        # Check if teacher already exists for this session + term
        existing = mongo.teachers.find_one({
            'email': email,
            'session': session_val,
            'term': term
        })
        if existing:
            flash(f'Teacher {name} already has a profile for {term} Term, {session_val}', 'danger')
            return redirect(url_for('admin.create_teacher'))

        # Insert new teacher profile
        teacher_data = {
            'name': name,
            'email': email,
            'phone': phone,
            'session': session_val,
            'term': term,
            'date_created': datetime.utcnow(),
            'created_by': session.get('admin_name', 'admin')  # if you track admin
        }

        mongo.teachers.insert_one(teacher_data)
        flash(f'Teacher "{name}" successfully created for {term} Term!', 'success')

        return redirect(url_for('admin.create_teacher'))

    # GET — show form
    # You can pre-fill current session/term or list available ones
    current_session = get_current_context()['session_name']  # Or make dynamic
    terms = ['First', 'Second', 'Third']

    return render_template('admin/create_teacher.html',
                           current_session=current_session,
                           terms=terms)


@admin_bp.route('/teachers/assign', methods=['GET', 'POST'])
@admin_required
def assign_teachers():
    # Get current or selected term context
    current_session = get_current_context()['session_name']  # Make dynamic later
    terms = ['First', 'Second', 'Third']
    selected_term = request.form.get('term') or request.args.get('term') or get_current_context()['term']

    # Fetch all active teachers for this term
    teachers = list(mongo.teachers.find({
        'session': current_session,
        'term': selected_term
    }).sort('name', 1))

    # Fetch all classes (assume you have a classes collection or hardcode)
    classes = ['JSS1', 'JSS2', 'JSS3', 'SSS1', 'SSS2', 'SSS3']  # Update as needed

    # Available subjects
    subjects = ['Mathematics', 'English Language', 'Basic Science', 'Basic Technology',
                'Social Studies', 'Civic Education', 'Physical Education', 'Biology',
                'Chemistry', 'Physics', 'Literature', 'Government', 'Economics']

    if request.method == 'POST':
        action = request.form.get('action')
        teacher_email = request.form.get('teacher_email')
        term = request.form.get('term')
        session_val = current_session

        if action == 'assign_subject':
            subject = request.form.get('subject')
            class_name = request.form.get('class')

            if not all([teacher_email, subject, class_name]):
                flash('All fields required for subject assignment', 'danger')
            else:
                # Check if already assigned
                existing = mongo.subject_assignments.find_one({
                    'teacher_email': teacher_email,
                    'subject': subject,
                    'class': class_name,
                    'session': session_val,
                    'term': term
                })
                if existing:
                    flash(f'{subject} already assigned to this teacher in {class_name}', 'warning')
                else:
                    mongo.subject_assignments.insert_one({
                        'teacher_email': teacher_email,
                        'subject': subject,
                        'class': class_name,
                        'session': session_val,
                        'term': term,
                        'date_assigned': datetime.utcnow()
                    })
                    flash(f'{subject} assigned successfully in {class_name}', 'success')

        elif action == 'assign_class_teacher':
            class_name = request.form.get('class')

            if not all([teacher_email, class_name]):
                flash('Select teacher and class', 'danger')
            else:
                # Remove any previous class teacher for this class/term
                mongo.class_assignments.delete_many({
                    'class': class_name,
                    'session': session_val,
                    'term': term
                })
                # Assign new
                mongo.class_assignments.insert_one({
                    'class': class_name,
                    'teacher_email': teacher_email,
                    'session': session_val,
                    'term': term,
                    'date_assigned': datetime.utcnow()
                })
                flash(f'Class teacher assigned for {class_name}', 'success')

        return redirect(url_for('admin.assign_teachers', term=term))

    # GET — show assignment page
    # Fetch current assignments for display
    subject_assignments = list(mongo.subject_assignments.find({
        'session': current_session,
        'term': selected_term
    }))

    class_assignments = list(mongo.class_assignments.find({
        'session': current_session,
        'term': selected_term
    }))
    class_teacher_map = {ca['class']: ca['teacher_email'] for ca in class_assignments}

    return render_template(
        'admin/assign_teachers.html',
        teachers=teachers,
        classes=classes,
        subjects=subjects,
        current_session=current_session,
        selected_term=selected_term,
        terms=terms,
        subject_assignments=subject_assignments,
        class_teacher_map=class_teacher_map
    )

@admin_bp.route('/term_enrollment', methods=['GET', 'POST'])
@admin_required
def term_enrollment():
    current_session = get_current_context()['session_name']  # Make dynamic later
    terms = ['First', 'Second', 'Third']
    classes = ['JSS1', 'JSS2', 'JSS3', 'SSS1', 'SSS2', 'SSS3']

    selected_term = request.form.get('term') or request.args.get('term') or get_current_context()['term']

    if request.method == 'POST':
        selected_students = request.form.getlist('student_select')  # admission numbers
        selected_class = request.form['class']

        enrolled_count = 0
        for adm_no in selected_students:
            student = mongo.students.find_one({'admission_number': adm_no})
            if student:
                # Upsert into term_enrollments
                mongo.term_enrollments.update_one(
                    {
                        'admission_number': adm_no,
                        'session': current_session,
                        'term': selected_term
                    },
                    {'$set': {
                        'name': student['name'],
                        'class': selected_class,
                        'session': current_session,
                        'term': selected_term,
                        'date_enrolled': datetime.utcnow()
                    }},
                    upsert=True
                )
                enrolled_count += 1

        flash(f'Successfully enrolled {enrolled_count} students in {selected_class} for {selected_term} Term!', 'success')
        return redirect(url_for('admin.term_enrollment', term=selected_term))

    # GET — show all students from master list
    all_students = list(mongo.students.find().sort('name', 1))

    # Currently enrolled in selected term
    enrolled_adms = set(
        doc['admission_number'] for doc in mongo.term_enrollments.find({
            'session': current_session,
            'term': selected_term
        })
    )

    return render_template(
        'admin/term_enrollment.html',
        students=all_students,
        enrolled_adms=enrolled_adms,
        classes=classes,
        current_session=current_session,
        selected_term=selected_term,
        terms=terms
    )

@admin_bp.route('/class_students/<class_name>')
@admin_required
def class_students(class_name):
    current_session = get_current_context()['session_name']  # Make dynamic
    current_term = get_current_context()['term']  # Make dynamic or from form

    # All students in this class for current term
    students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': current_session,
        'term': current_term
    }).sort('name', 1))

    if not students:
        flash('No students enrolled in this class for current term', 'info')

    return render_template(
        'admin/class_students.html',
        class_name=class_name,
        students=students,
        current_session=current_session,
        current_term=current_term
    )

@admin_bp.route('/save_student_results', methods=['POST'])
@admin_required
def save_student_results():
    adm_no = request.form['adm_no']
    current_session = get_current_context()['session_name']
    current_term = get_current_context()['term']

    for key in request.form:
        if key.startswith('ca1_'):
            subject = key.split('_')[1]
            ca1 = float(request.form.get(f'ca1_{subject}', 0))
            ca2 = float(request.form.get(f'ca2_{subject}', 0))
            exam = float(request.form.get(f'exam_{subject}', 0))
            total = ca1 + ca2 + exam
            if current_term == 'Third':
                cum1 = float(request.form.get(f'cum1_{subject}', 0))
                cum2 = float(request.form.get(f'cum2_{subject}', 0))
                total = round((cum1 + cum2 + total) / 3, 2)

            mongo.results.update_one(
                {'admission_number': adm_no, 'subject': subject, 'session': current_session, 'term': current_term},
                {'$set': {'ca1': ca1, 'ca2': ca2, 'exam': exam, 'total': total}},
                upsert=True
            )

    flash('Student results updated successfully!', 'success')
    return redirect(url_for('admin.edit_student', adm_no=adm_no))

@admin_bp.route('/edit_student/<regex:adm_no>')
@admin_required
def edit_student(adm_no):
    current_session = get_current_context()['session_name']
    current_term = get_current_context()['term']

    student = mongo.students.find_one({'admission_number': adm_no})
    enrollment = mongo.term_enrollments.find_one({'admission_number': adm_no})

    # All results for this student
    results = list(mongo.results.find({
        'admission_number': adm_no,
        'session': current_session,
        'term': current_term
    }).sort('subject', 1))

    return render_template(
        'admin/edit_student.html',
        student=student,
        enrollment=enrollment,
        results=results,
        current_term=current_term
    )

@admin_bp.route('/classes')
@admin_required
def classes_overview():
    current_session = get_current_context()['session_name'] # Make dynamic if needed
    current_term = get_current_context()['term']  # Make dynamic

    # Get all distinct classes that have students enrolled this term
    classes = mongo.term_enrollments.distinct('class', {
        'session': current_session,
        'term': current_term
    })

    classes.sort()  # Nice alphabetical order

    return render_template(
        'admin/classes_overview.html',
        classes=classes,
        current_session=current_session,
        current_term=current_term
    )

@admin_bp.route('/subjects/create', methods=['GET', 'POST'])
@admin_required
def create_subject():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip().upper()
        description = request.form.get('description', '').strip()
        is_active = request.form.get('is_active') == 'on'

        if not name or not code:
            flash('Subject name and code are required', 'danger')
            return redirect(url_for('admin.create_subject'))

        # Check for duplicate code (unique identifier)
        if mongo.db.subjects.find_one({'code': code}):
            flash(f'Subject code "{code}" already exists', 'danger')
            return redirect(url_for('admin.create_subject'))

        mongo.subjects.insert_one({
            'name': name.title(),
            'code': code,
            'description': description,
            'is_active': is_active,
            'date_created': datetime.utcnow()
        })

        flash(f'Subject "{name}" ({code}) created successfully!', 'success')
        return redirect(url_for('admin.subjects_list'))

    return render_template('admin/create_subject.html')

@admin_bp.route('/subjects')
@admin_required
def subjects_list():
    subjects = list(mongo.subjects.find().sort('name', 1))
    return render_template('admin/subjects_list.html', subjects=subjects)