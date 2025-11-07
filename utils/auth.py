# utils/auth.py
from functools import wraps
from flask import session, redirect, url_for, request, flash

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
    def wrap(*args, **kwargs):
        if session.get('role') != 'teacher':
            return redirect(url_for('admin.teacher_login'))
        return f(*args, **kwargs)
    return wrap