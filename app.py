# app.py
from flask import Flask
from config import Config
from extensions import mongo, init_mongo
from flask.json.provider import DefaultJSONProvider
from werkzeug.routing import BaseConverter
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
            
# Custom converter to allow slashes and other characters in URL parts
class AdmissionNumberConverter(BaseConverter):
    regex = r'[\w/]+'  # allow letters, digits, underscore, slash

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = app.config['SECRET_KEY']
    app.json = MongoJSONProvider(app)
    # Register the converter globally
    app.url_map.converters['regex'] = AdmissionNumberConverter
    
    # Initialize extensions
    init_mongo(app)

    # Register blueprints (import here to avoid circular)
    from routes.main import main_bp
    from routes.admin import admin_bp
    from routes.student import student_bp
    from routes.teacher import teacher_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(teacher_bp, url_prefix='/teacher')


    

    return app



if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)

    