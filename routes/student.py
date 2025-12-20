# routes/student.py
from flask import Blueprint, render_template, request, jsonify, session , redirect, url_for, flash
from extensions import mongo
from bson import ObjectId
import bcrypt

student_bp = Blueprint('student', __name__)  # Optional: clean URL

@student_bp.route('/', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        adm_no = request.form.get('admission_number')
        password = request.form.get('password')

        if not adm_no or not password:
            flash('Please enter both admission number and password.', 'error')
            return redirect(url_for('student.search'))

        student = mongo.db.students.find_one({'admission_number': adm_no.strip()})

        if not student:
            flash('Invalid admission number or password.', 'error')
            return redirect(url_for('student.search'))

        # Critical Fix: Ensure stored password is treated as bytes
        stored_hash = student.get('password')

        if not stored_hash:
            flash('Account error — contact admin.', 'error')
            return redirect(url_for('student.search'))

        # If you stored as decoded string (common issue)
        if isinstance(stored_hash, str):
            stored_hash_bytes = stored_hash.encode('utf-8')
        else:
            stored_hash_bytes = stored_hash  # already bytes (rare)

        # Now check
        # In the POST success section of search()
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash_bytes):
             # CRITICAL: Store the ObjectId as string
            session['student_id'] = str(student['_id'])
            session['adm_no'] = str(student['admission_number'])
    
          
    
            flash('Welcome back! Loading your dashboard...', 'success')
            return redirect(url_for('student.dashboard'))  # Make sure this matches exactly
        else:
            flash('Invalid admission number or password.', 'error')
            return redirect(url_for('student.search'))

    return render_template('student/search.html')

@student_bp.route('/dashboard')
def dashboard():
    if 'adm_no' not in session:
        return redirect(url_for('student.search'))

   
    student = mongo.students.find_one({'admission_number': session['adm_no']})     
    sessions = list(mongo.sessions.find({}, {'name': 1, '_id': 0}).sort('name'))
    terms = list(mongo.terms.find({}, {'name': 1, '_id': 0}).sort('order'))

    
    return render_template('student/dashboard.html', student=student, sessions=sessions, terms=terms)
    

@student_bp.route('/results')
def results():
    # Security: Ensure student is logged in
    if 'adm_no' not in session:
        return jsonify({'error': 'Please login first'}), 401

    session_name = request.args.get('session')
    term = request.args.get('term')

    if not session_name or not term:
        return jsonify({'error': 'Please select both session and term'}), 400

    adm_no = session['adm_no']

    # Fetch all results for this session + term to calculate class position
    all_results = list(mongo.results.find({
        'session': session_name,
        'term': term
    }))

    # Calculate total scores for ranking
    totals = []
    for r in all_results:
        total_score = sum(
            (s.get('score_CA1', 0) + s.get('score_CA2', 0) + s.get('score_Exam', 0))
            for s in r.get('subjects', [])
        )
        totals.append({
            'admission_number': r['admission_number'],
            'total': total_score
        })

    # Sort descending to get positions
    totals.sort(key=lambda x: x['total'], reverse=True)
    position = next(
        (idx + 1 for idx, t in enumerate(totals) if t['admission_number'] == adm_no),
        None
    )

    # Fetch the logged-in student's result
    student_result = mongo.results.find_one({
        'admission_number': adm_no,
        'session': session_name,
        'term': term
    })

    if not student_result:
        return jsonify({'results': []})  # Triggers "No results found" in frontend

    # Attach position to result
    student_result['position'] = position

    # Return in expected format for your JS
    return jsonify({'results': [student_result]})
    
@student_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('student.search'))