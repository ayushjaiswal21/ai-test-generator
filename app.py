import os
import time
import json
import logging
import requests
import mysql.connector
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from mysql.connector import Error as DBError

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
CORS(app)

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database operations"""
    
    @staticmethod
    def get_connection():
        try:
            return mysql.connector.connect(
                host=os.getenv('DB_HOST'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                database=os.getenv('DB_NAME'),
                port=int(os.getenv('DB_PORT', 3306)),
                connect_timeout=5
            )
        except DBError as e:
            logger.error(f"Database connection failed: {str(e)}")
            return None

    @staticmethod
    def save_questions(questions):
        """Save generated questions to database"""
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
                        correct_answer TEXT NOT NULL,
                        question_type VARCHAR(50) NOT NULL,
                        difficulty VARCHAR(50) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.executemany(
                    """INSERT INTO questions 
                    (topics, question_text, correct_answer, question_type, difficulty) 
                    VALUES (%s, %s, %s, %s, %s)""",
                    questions
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

class QuizGenerator:
    """Handles question generation using Ollama"""
    
    _last_request_time = 0
    
    def __init__(self):
        self.api_url = "http://localhost:11435/api/generate"
        self.model = "mistral"
        self.timeout = 180  # Increased from 90 to 180 seconds
        self.max_questions = 10
        self.min_request_interval = 1  # Minimum interval between requests in seconds

    def generate_questions(self, prompt_data):
        try:
            # Validate input
            if not prompt_data.get('topics'):
                raise ValueError("At least one topic is required")
                
            question_type = prompt_data.get('type', 'multiple choice').lower()
            num_questions = min(int(prompt_data.get('num_questions', 1)), self.max_questions)
            difficulty = prompt_data.get('difficulty', 'medium').lower()

            # Rate limiting
            current_time = time.time()
            elapsed = current_time - self._last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self._last_request_time = time.time()

            # Build prompt
            prompt = f"""Generate exactly {num_questions} {difficulty} difficulty {question_type} questions about {', '.join(prompt_data['topics'])}.
            
            Format each question as follows:
            1. Question text?
            ||CorrectAnswer
            
            For multiple choice, include options like:
            1. Question text?
            A) Option 1
            B) Option 2
            C) Option 3
            D) Option 4
            ||CorrectLetter
            
            Return ONLY the questions in this format, one per line.
            Do NOT include any additional text or explanations."""

            # Make API request to local Ollama
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.7}
                },
                timeout=self.timeout
            )
            response.raise_for_status()

            # Parse response
            generated_text = response.json().get("response", "")
            logger.debug(f"Raw generated text:\n{generated_text}")
            
            questions = []
            current_question = []
            current_answer = None

            for line in generated_text.split('\n'):
                line = line.strip()
                if '||' in line:
                    # Split the line into question part and answer
                    parts = line.split('||', 1)
                    question_part = parts[0].strip()
                    answer_part = parts[1].strip()
                    
                    if question_part:
                        current_question.append(question_part)
                    
                    if current_question:
                        question_text = '\n'.join(current_question)
                        questions.append((question_text, answer_part))
                        current_question = []
                else:
                    # Check if the line starts a new question (e.g., "1. ...")
                    if line and line[0].isdigit() and current_question:
                        logger.warning(f"Incomplete question: {' '.join(current_question)}")
                        current_question = []
                    if line:
                        current_question.append(line)
            
            if current_question:
                logger.warning(f"Unprocessed question lines: {' '.join(current_question)}")

            if not questions:
                raise ValueError("No valid questions found in response")
                
            logger.debug(f"Parsed questions: {questions}")
            return questions[:num_questions], None
            
        except Exception as e:
            logger.error(f"Generation failed: {str(e)}", exc_info=True)
            return None, str(e)

# Initialize components
quiz_generator = QuizGenerator()

@app.route('/')
def home():
    return render_template('index.html')

@app.route("/api/generate-quiz", methods=["POST"])
def generate_quiz():
    """Endpoint for generating quiz questions"""
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        logger.debug(f"Received request data: {data}")
        
        if not data.get('topics'):
            return jsonify({"error": "At least one topic required"}), 400

        questions, error = quiz_generator.generate_questions(data)
        if error:
            return jsonify({"error": error}), 400

        db_questions = [
            (
                json.dumps(data['topics']),
                question,
                answer,
                data.get('type', 'multiple choice'),
                data.get('difficulty', 'medium')
            )
            for question, answer in questions
        ]

        success, db_error = DatabaseManager.save_questions(db_questions)
        
        response = {
            "success": True,
            "questions": [{"question": q[1], "answer": q[2]} for q in db_questions],
            "count": len(db_questions)
        }
        
        if not success:
            response.update({
                "warning": "Questions generated but not saved",
                "db_error": db_error
            })
            return jsonify(response), 207
            
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    # Verify required environment variables
    required_vars = ['DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME']
    if missing := [var for var in required_vars if not os.getenv(var)]:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        exit(1)

    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Create basic index.html if it doesn't exist
    if not os.path.exists('templates/index.html'):
        with open('templates/index.html', 'w') as f:
            f.write("""<!DOCTYPE html>
<html>
<head>
    <title>Quiz Generator</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        pre { background: #f4f4f4; padding: 10px; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>Quiz Generator API</h1>
    <p>POST to <code>/api/generate-quiz</code> with JSON payload:</p>
    <pre>
{
    "topics": ["history", "science"],
    "num_questions": 3,
    "type": "multiple choice",
    "difficulty": "medium"
}</pre>
</body>
</html>""")

    # Run the application
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('DEBUG', 'false').lower() == 'true'
    )