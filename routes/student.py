# routes/student.py
from flask import Blueprint, render_template, request, jsonify
from extensions import mongo
from bson.objectid import ObjectId

student_bp = Blueprint('student', __name__)

@student_bp.route('/', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        # FIXED: Use 'admission_number' consistently
        adm_no = request.form.get('admission_number')
        if not adm_no:
            return jsonify({'error': 'Admission number is required'}), 400

        student = mongo.students.find_one({'admission_number': adm_no.strip()})
        if not student:
            return jsonify({'error': 'Student not found'}), 404

        results = list(mongo.results.find({'student_id': student['_id']}).sort('uploaded_at', -1))
        return jsonify([{
        'session': r['session'],
        'term': r['term'],
        'subjects': r['subjects'],
        'uploaded_at': r['uploaded_at'].isoformat() if 'uploaded_at' in r else None,
        '_id': str(r['_id'])  # ← Convert ObjectId to string
    } for r in results])

    return render_template('student/search.html')