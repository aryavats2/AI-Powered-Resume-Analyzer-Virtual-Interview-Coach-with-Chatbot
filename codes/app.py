import os
import sqlite3
import requests
import fitz  # PyMuPDF for PDF text extraction
from flask import Flask, request, jsonify, render_template, g
from werkzeug.utils import secure_filename

app = Flask(__name__)

# -------------------- CONFIGURATION --------------------


INTERVIEW_DB = "interview_history.db"  # For resume/interview coach data
CHAT_DB = "chat_history.db"            # For SuperGpt chat history
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global variable to store extracted PDF text for SuperGpt chat context
uploaded_pdf_text = ""

# -------------------- DATABASE FUNCTIONS --------------------
def get_db(db_name):
    """Connects to the specified database and returns the connection object."""
    key = '_database_' + db_name
    if not hasattr(g, key):
        conn = sqlite3.connect(db_name, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        setattr(g, key, conn)
    return getattr(g, key)

def init_db():
    """Initializes both databases (interview and chat history)."""
    with app.app_context():
        # Initialize Interview History Database
        db_int = get_db(INTERVIEW_DB)
        cursor_int = db_int.cursor()
        cursor_int.execute('''
            CREATE TABLE IF NOT EXISTS interview_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT,
                user_response TEXT,
                rating TEXT,
                feedback TEXT
            )
        ''')
        db_int.commit()

        # Initialize Chat History Database
        db_chat = get_db(CHAT_DB)
        cursor_chat = db_chat.cursor()
        cursor_chat.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_message TEXT,
                bot_reply TEXT
            )
        ''')
        db_chat.commit()

@app.teardown_appcontext
def close_connection(exception):
    """Closes all database connections after each request."""
    for db_name in [INTERVIEW_DB, CHAT_DB]:
        key = '_database_' + db_name
        db = getattr(g, key, None)
        if db is not None:
            db.close()

# -------------------- HELPER FUNCTIONS --------------------
def allowed_file(filename):
    """Checks if the uploaded file has a valid extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_obj):
    """Extracts text from an uploaded PDF file object."""
    try:
        doc = fitz.open(stream=file_obj.read(), filetype="pdf")
        text = "\n".join([page.get_text("text") for page in doc])
        return text.strip() if text.strip() else "No text found in PDF."
    except Exception as e:
        print("Error reading PDF:", e)
        return ""

# -------------------- ROUTES --------------------
@app.route("/")
def index():
    """Renders the homepage (index.html) for interview coach."""
    return render_template("index.html")

# ----- INTERVIEW COACH FUNCTIONALITY -----
@app.route("/upload_resume", methods=["POST"])
def upload_resume():
    """Handles resume upload and extracts text for interview question generation."""
    if "resume" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["resume"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    try:
        with open(file_path, "rb") as f:
            resume_text = extract_text_from_pdf(f)
    except Exception as e:
        return jsonify({"error": f"Failed to extract text: {str(e)}"}), 500

    print("Extracted Resume Text:", resume_text)  # Debug output

    if not resume_text:
        return jsonify({"error": "Failed to extract text from resume"}), 500

    return jsonify({"resume_text": resume_text})

@app.route("/ask", methods=["POST"])
def get_question():
    """Generates an interview question based on the uploaded resume."""
    data = request.json
    resume_text = data.get("resume_text", "")
    if not resume_text:
        return jsonify({"error": "No resume text provided"}), 400

    system_prompt = (
        f"You are an AI HR interviewer. Based on this resume:\n{resume_text}\n"
        "Ask a job-specific technical or behavioral interview question."
    )
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "system", "content": system_prompt}],
        "temperature": 0.7
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    print("ASK Payload:", payload)  # Debug log
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload)
        print("ASK API Response:", response.text)  # Debug log
        question = response.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"question": question})
    except Exception as e:
        return jsonify({"error": f"API request failed: {str(e)}"}), 500

@app.route("/evaluate", methods=["POST"])
def evaluate_response():
    """Evaluates the candidate's response and provides AI feedback."""
    data = request.json
    question = data.get("question", "")
    user_response = data.get("response", "")
    if not question or not user_response:
        return jsonify({"error": "Invalid input"}), 400

    system_prompt = (
        f"Rate this response and provide feedback:\n\nQuestion: {question}\nUser Response: {user_response}"
    )
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "system", "content": system_prompt}],
        "temperature": 0.7
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload)
        result = response.json()["choices"][0]["message"]["content"].strip()

        db_int = get_db(INTERVIEW_DB)
        cursor = db_int.cursor()
        cursor.execute(
            "INSERT INTO interview_history (question, user_response, rating, feedback) VALUES (?, ?, ?, ?)",
            (question, user_response, "AI Rated", result)
        )
        db_int.commit()
        return jsonify({"rating": "AI Rated", "feedback": result})
    except Exception as e:
        return jsonify({"error": f"API request failed: {str(e)}"}), 500

# ----- KIIT CHATBOT (SUPER GPT CHAT) FUNCTIONALITY -----
@app.route("/upload_pdf", methods=["POST"])
def upload_pdf_chat():
    """Handles PDF upload and extracts text for SuperGpt chat."""
    global uploaded_pdf_text
    if "file" not in request.files:
        return jsonify({"message": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "" or not file.filename.endswith(".pdf"):
        return jsonify({"message": "Invalid file type"}), 400

    try:
        uploaded_pdf_text = extract_text_from_pdf(file)
        return jsonify({"message": "PDF uploaded successfully", "uploaded_text": uploaded_pdf_text})
    except Exception as e:
        return jsonify({"message": f"Error processing PDF: {str(e)}"}), 500

@app.route("/super_gpt_chat", methods=["GET"])
def super_gpt_chat():
    """Renders the SuperGpt chat page (chat.html)."""
    return render_template("chat.html")

@app.route("/chat", methods=["GET", "POST"])
def chat_route():
    """Handles chat queries for SuperGpt."""
    global uploaded_pdf_text
    if request.method == "GET":
        return render_template("chat.html")
    
    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "Please enter a message"}), 400

    system_prompt = (
        f"You are KiitGPT, an AI assistant for KIIT students. Answer queries based on uploaded documents if available, "
        f"or provide normal responses if no PDF is uploaded.\n\n"
        f"Uploaded PDF Content:\n\n{uploaded_pdf_text}\n\n"
        if uploaded_pdf_text else "You are KiitGPT, an AI assistant for KIIT students. Arya Vats and his team developed you."
    )
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload)
        bot_reply = response.json()["choices"][0]["message"]["content"].strip()

        db_chat = get_db(CHAT_DB)
        cursor = db_chat.cursor()
        cursor.execute("INSERT INTO chat_history (user_message, bot_reply) VALUES (?, ?)", (user_message, bot_reply))
        db_chat.commit()
        return jsonify({"reply": bot_reply})
    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"}), 500

@app.route("/history", methods=["GET"])
def get_chat_history():
    """Fetches the stored chat history from the chat database."""
    db_chat = get_db(CHAT_DB)
    cursor = db_chat.cursor()
    cursor.execute("SELECT user_message, bot_reply FROM chat_history ORDER BY id DESC")
    history = cursor.fetchall()
    chat_list = [{"user": row["user_message"], "bot": row["bot_reply"]} for row in history]
    return jsonify({"history": chat_list})

# -------------------- INITIALIZE DATABASE AND RUN THE APP --------------------
init_db()

if __name__ == "__main__":
    app.run(debug=True)
