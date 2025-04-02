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

# Set up logging with DEBUG level as requested
logging.basicConfig(
    level=logging.DEBUG,  # explicitly set to DEBUG for more verbosity
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__, template_folder='templates')
CORS(app)

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
                connect_timeout=5
            )
        except DBError as e:
            logger.error(f"Database connection failed: {str(e)}")
            return None

    @staticmethod
    def save_questions(questions):
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
    _last_request_time = 0
    
    def __init__(self):
        self.api_url = "http://localhost:11434/api/generate"
        self.model = "mistral"
        self.timeout = 180
        self.max_questions = 20
        self.min_request_interval = 1

    def generate_questions(self, prompt_data):
        try:
            if not prompt_data.get('topics'):
                raise ValueError("At least one topic is required")
                
            question_type = prompt_data.get('type', 'multiple choice').lower()
            num_questions = min(int(prompt_data.get('num_questions', 1)), self.max_questions)
            difficulty = prompt_data.get('difficulty', 'medium').lower()

            current_time = time.time()
            elapsed = current_time - self._last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self._last_request_time = time.time()

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

            logger.debug(f"Sending request to API: {self.api_url}")
            logger.debug(f"Request prompt: {prompt}")
            
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
            
            print(f"Raw API response status code: {response.status_code}")
            print(f"Raw API response content: {response.text[:500]}...")
            
            response.raise_for_status()
            
            response_data = response.json()
            print(f"API response type: {type(response_data)}")
            print(f"API response keys: {response_data.keys() if isinstance(response_data, dict) else 'Not a dict'}")
            
            generated_text = ""
            if isinstance(response_data, dict):
                generated_text = response_data.get("response", "")
                if not isinstance(generated_text, str):
                    print(f"Warning: Response is not a string but a {type(generated_text)}")
                    generated_text = str(generated_text)
            else:
                print(f"Warning: Response is not a dictionary but a {type(response_data)}")
                generated_text = str(response_data)
            
            logger.debug(f"Extracted generated text (first 200 chars):\n{generated_text[:200]}...")
            print(f"Full generated text:\n{generated_text}")
            
            questions = []
            question_blocks = []
            
            if '1.' in generated_text:
                import re
                question_blocks = re.split(r'\n\s*\d+\.', generated_text)
                question_blocks = [block.strip() for block in question_blocks if block.strip()]
                if question_blocks and not question_blocks[0].startswith('1.'):
                    question_blocks.pop(0) if not '||' in question_blocks[0] else None
            else:
                question_blocks = [block.strip() for block in generated_text.split('\n\n') if block.strip()]
            
            print(f"Found {len(question_blocks)} potential question blocks")
            
            for block in question_blocks:
                if '||' in block:
                    parts = block.split('||', 1)
                    question_text = parts[0].strip()
                    answer_text = parts[1].strip()
                    
                    # Check for invalid content
                    if '[object Object]' in question_text or '[object Object]' in answer_text:
                        print(f"Skipping invalid block with [object Object]: {block[:100]}...")
                        continue
                    if not question_text or not answer_text:
                        print(f"Skipping empty question/answer in block: {block[:100]}...")
                        continue
                    
                    questions.append((question_text, answer_text))
                    print(f"Parsed question: {question_text[:50]}... Answer: {answer_text}")
                else:
                    print(f"Skipping block without delimiter: {block[:50]}...")
            
            if not questions:
                print("Trying line-by-line parsing")
                current_question = []
                for line in generated_text.split('\n'):
                    line = line.strip()
                    if '||' in line:
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
                        if line and line[0].isdigit() and '. ' in line and current_question:
                            current_question = [line]
                        elif line:
                            current_question.append(line)
                if current_question:
                    print(f"Unprocessed lines: {current_question}")
            
            if not questions:
                raise ValueError("No valid questions found in response")
                
            print(f"Successfully parsed {len(questions)} questions")
            return questions[:num_questions], None
            
        except Exception as e:
            logger.error(f"Generation failed: {str(e)}", exc_info=True)
            return None, str(e)

quiz_generator = QuizGenerator()

@app.route('/')
def home():
    return render_template('index.html')

@app.route("/api/generate-quiz", methods=["POST"])
def generate_quiz():
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

        if not questions:
            return jsonify({"error": "No questions could be generated"}), 400

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
            "questions": [{"question": q, "answer": a} for q, a in questions],
            "count": len(questions)
        }
        
        # Debugging: Print final questions to check data
        print("\nFinal questions to be sent in response:")
        for idx, qa in enumerate(response["questions"]):
            print(f"Question {idx + 1}: {qa['question']}")
            print(f"Answer {idx + 1}: {qa['answer']}\n")
        
        if not success:
            response.update({
                "warning": "Questions generated but not saved",
                "db_error": db_error
            })
            return jsonify(response), 207
        
        # Fixed: Return 200 success status code instead of 500
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    required_vars = ['DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME']
    if missing := [var for var in required_vars if not os.getenv(var)]:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        exit(1)

    os.makedirs('templates', exist_ok=True)

    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('DEBUG', 'true').lower() == 'true'
    )