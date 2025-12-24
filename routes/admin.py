# routes/admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import mongo
from utils.auth import admin_required
from utils.sessions import get_current_context, get_active_enrollments, find_student_by_admission
from bson import ObjectId
import bcrypt
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Hardcoded admin (consider moving to DB later)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = bcrypt.hashpw("gptschool2025".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

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
        'admin/enroll_students.html',
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


@admin_bp.route('/toggle-result-visibility/<student_id>', methods=['POST'])
@admin_required
def toggle_result_visibility(student_id):
    student = mongo.students.find_one({'_id': ObjectId(student_id)})
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('admin.manage_students'))
    new_status = not student.get('results_visible', True)
    mongo.students.update_one({'_id': ObjectId(student_id)}, {'$set': {'results_visible': new_status}})
    action = "blocked from" if not new_status else "allowed to"
    flash(f'{student["name"]} has been {action} viewing results', 'success')
    return redirect(request.referrer or url_for('admin.manage_students'))


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
                "term": "First",
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