# utils/auth.py
from functools import wraps
from flask import session, redirect, url_for, flash
from extensions import mongo  # Needed to verify student exists in DB

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access admin panel.', 'error')
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'teacher' or not session.get('teacher_email'):
            flash('Please log in as a teacher', 'error')
            return redirect(url_for('teacher.login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== STUDENT VERIFICATION DECORATOR ====================
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'adm_no' not in session:
            flash('Please log in to view your results', 'error')
            return redirect(url_for('student.search'))

        # Extra safety: verify the student record still exists
        student = mongo.students.find_one({'admission_number': session['adm_no']})
        if not student:
            flash('Student account not found. Please contact the school.', 'error')
            session.clear()
            return redirect(url_for('student.search'))

        return f(*args, **kwargs)
    return decorated_function

# ======================== Calculating position
def calculate_position_in_class(adm_no, session, term):
    # Get the student's class for this session/term
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': session,
        'term': term
    })
    if not enrollment or 'class' not in enrollment:
        return None, 0

    student_class = enrollment['class']

    # Get ALL students in the SAME CLASS for this session + term
    class_enrollments = list(mongo.term_enrollments.find({
        'session': session,
        'term': term,
        'class': student_class
    }))

    if not class_enrollments:
        return None, 0

    student_totals = {}

    for enr in class_enrollments:
        student_adm = enr['admission_number']
        results = list(mongo.results.find({
            'admission_number': student_adm,
            'session': session,
            'term': term
        }))

        if not results:
            student_totals[student_adm] = 0
            continue

        # Calculate adjusted average
        total = 0.0
        if term == 'Third':
            for r in results:
                ca1 = float(r.get('ca1', 0))
                ca2 = float(r.get('ca2', 0))
                exam = float(r.get('exam', 0))
                cum1 = float(r.get('cumulative1', 0))
                cum2 = float(r.get('cumulative2', 0))
                total += (cum1 + cum2 + ca1 + ca2 + exam) / 3
        else:
            for r in results:
                total += float(r.get('total', 0))

        adjusted_average = round(total / len(results), 2)
        student_totals[student_adm] = adjusted_average

    # Sort by adjusted average (descending)
    sorted_students = sorted(student_totals.items(), key=lambda x: x[1], reverse=True)

    # Find position
    position = None
    for rank, (student_id, avg) in enumerate(sorted_students, 1):
        if student_id == adm_no:
            position = rank
            break

    class_size = len(sorted_students)
    return position, class_size