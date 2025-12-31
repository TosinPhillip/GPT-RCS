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