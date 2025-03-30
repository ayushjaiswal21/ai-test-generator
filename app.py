import mysql.connector
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
from mysql.connector import Error as DBError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from requests.exceptions import RequestException
import os
import json
import logging
from datetime import datetime

load_dotenv()

app = Flask(__name__, template_folder='templates')
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    MAX_QUESTIONS = 20
    OPENAI_TIMEOUT = (10, 60)
    DB_CONNECT_TIMEOUT = 5
    OPENAI_MODEL = "gpt-3.5-turbo"
    MAX_RETRIES = 3

class DatabaseManager:
    @staticmethod
    def get_connection():
        try:
            return mysql.connector.connect(
                host=os.getenv('DB_HOST'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                database=os.getenv('DB_NAME'),
                port=int(os.getenv('DB_PORT', 3306)),
                connect_timeout=Config.DB_CONNECT_TIMEOUT
            )
        except DBError as e:
            logger.error(f"Database connection failed: {str(e)}")
            return None

    @staticmethod
    def save_questions(questions, metadata):
        db = DatabaseManager.get_connection()
        if not db:
            return False, "Database unavailable"
        
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS questions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        topics JSON NOT NULL,
                        question_text TEXT NOT NULL,
                        question_type VARCHAR(50) NOT NULL,
                        difficulty VARCHAR(50) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.executemany(
                    "INSERT INTO questions (topics, question_text, question_type, difficulty) VALUES (%s, %s, %s, %s)",
                    [(json.dumps(metadata['topics']), q, metadata['type'], metadata['difficulty']) for q in questions]
                )
                db.commit()
                return True, ""
        except Exception as e:
            db.rollback()
            logger.error(f"Database error: {str(e)}")
            return False, str(e)
        finally:
            if db.is_connected():
                db.close()

class OpenAIService:
    RETRY_CONFIG = {
        'stop': stop_after_attempt(Config.MAX_RETRIES),
        'wait': wait_exponential(multiplier=1, min=5, max=60),
        'retry': retry_if_exception_type(RequestException),
        'reraise': True
    }

    @classmethod
    @retry(**RETRY_CONFIG)
    def generate_questions(cls, prompt):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": Config.OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1500
                },
                timeout=Config.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            return [q.strip() for q in content.split('\n') if q.strip()], None
        except RequestException as e:
            logger.error(f"API request failed: {str(e)}")
            return None, f"API request failed: {str(e)}"
        except Exception as e:
            logger.error(f"Processing error: {str(e)}")
            return None, f"Processing error: {str(e)}"

@app.route('/')
def home():
    return render_template('index.html')

@app.route("/api/generate-quiz", methods=["POST"])
def generate_quiz():
    start_time = datetime.now()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request payload missing"}), 400

        errors = {}
        if not isinstance(data.get('topics'), list):
            errors['topics'] = "Must be a list"
        if not isinstance(data.get('type'), str):
            errors['type'] = "Must be a string"
        if not isinstance(data.get('difficulty'), str):
            errors['difficulty'] = "Must be a string"
        if not isinstance(data.get('num_questions'), int):
            errors['num_questions'] = "Must be an integer"
        
        if errors:
            return jsonify({"error": "Invalid input", "details": errors}), 400
            
        num_questions = data['num_questions']
        if not 1 <= num_questions <= Config.MAX_QUESTIONS:
            return jsonify({"error": f"num_questions must be between 1 and {Config.MAX_QUESTIONS}"}), 400

        questions, error = OpenAIService.generate_questions(
            f"Generate {num_questions} {data['difficulty']} {data['type']} questions about {', '.join(data['topics'])}"
        )
        if error:
            return jsonify({"error": error}), 500

        success, db_error = DatabaseManager.save_questions(
            questions,
            {
                "topics": data['topics'],
                "type": data['type'],
                "difficulty": data['difficulty']
            }
        )

        response_data = {
            "success": True,
            "questions": questions,
            "count": len(questions),
            "processing_time": str(datetime.now() - start_time)
        }

        if not success:
            response_data.update({
                "warning": "Questions generated but not saved",
                "db_error": db_error
            })
            return jsonify(response_data), 207

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/questions", methods=["GET"])
def get_questions():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, max(1, int(request.args.get('per_page', 10))))
        offset = (page - 1) * per_page

        db = DatabaseManager.get_connection()
        if not db:
            return jsonify({"error": "Database unavailable"}), 503

        with db.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT * FROM questions ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (per_page, offset)
            )
            questions = cursor.fetchall()
            cursor.execute("SELECT COUNT(*) AS total FROM questions")
            total = cursor.fetchone()['total']

        return jsonify({
            "data": questions,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }), 200

    except Exception as e:
        logger.error(f"Failed to fetch questions: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if 'db' in locals() and db.is_connected():
            db.close()

if __name__ == "__main__":
    os.makedirs('templates', exist_ok=True)
    
    if not os.path.exists('templates/index.html'):
        with open('templates/index.html', 'w') as f:
            f.write("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Quiz Generator</title>
            </head>
            <body>
                <h1>Quiz Generator API</h1>
                <p>Use POST /api/generate-quiz with JSON payload</p>
                <p>Use GET /api/questions to retrieve saved questions</p>
            </body>
            </html>
            """)

    app.run(
        host='0.0.0.0', 
        port=int(os.getenv('PORT', 5000)), 
        debug=os.getenv('DEBUG', 'false').lower() == 'true'
    )