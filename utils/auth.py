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
def calculate_position_in_class(adm_no, session_name, term_name):
    """
    Returns the student's position in their class for the given session/term
    based on overall average across subjects.
    """
    # Get student's current class
    enrollment = mongo.term_enrollments.find_one({
        'admission_number': adm_no,
        'session': session_name,
        'term': term_name
    })
    if not enrollment:
        return None, None

    class_name = enrollment['class']

    # Get all students in the same class/term
    class_students = list(mongo.term_enrollments.find({
        'class': class_name,
        'session': session_name,
        'term': term_name
    }))

    if not class_students:
        return None, len(class_students)

    class_size = len(class_students)

    # Calculate average for each student
    student_averages = []
    for st in class_students:
        st_adm = st['admission_number']
        results = list(mongo.results.find({
            'admission_number': st_adm,
            'session': session_name,
            'term': term_name
        }))

        if not results:
            avg = 0.0
        else:
            totals = [r.get('total', 0) for r in results]
            avg = sum(totals) / len(totals)

        student_averages.append((st_adm, avg))

    # Sort descending by average
    sorted_averages = sorted(student_averages, key=lambda x: x[1], reverse=True)

    # Find position (1-based, ties get same rank, next skips)
    position = None
    current_rank = 1
    prev_avg = None

    for i, (st_adm, avg) in enumerate(sorted_averages, 1):
        if i > 1 and avg < prev_avg:
            current_rank = i
        if st_adm == adm_no:
            position = current_rank
            break
        prev_avg = avg

    return position, class_size