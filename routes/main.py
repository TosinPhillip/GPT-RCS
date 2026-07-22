# routes/main.py
from flask import Blueprint, render_template
from extensions import mongo
from routes.books import BOOKS_DATA
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    return render_template('main/home.html')

@main_bp.route('/books')
def books():
    # Fetch from MongoDB (admin can update via dashboard later)
    books_data = list(mongo.books.find()) or BOOKS_DATA
    
    return render_template('books.html', books=BOOKS_DATA)