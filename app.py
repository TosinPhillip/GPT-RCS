# app.py
from flask import Flask
from config import Config
from extensions import mongo, init_mongo
from flask.json.provider import DefaultJSONProvider
from bson import ObjectId
from datetime import datetime

class MongoJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return super().default(obj)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config['SECRET_KEY']
    app.json = MongoJSONProvider(app)
    
    # Initialize extensions
    init_mongo(app)

    # Register blueprints (import here to avoid circular)
    from routes.admin import admin_bp
    from routes.student import student_bp
    from routes.teacher import teacher_bp
    
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(student_bp, url_prefix='/')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')
    

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)