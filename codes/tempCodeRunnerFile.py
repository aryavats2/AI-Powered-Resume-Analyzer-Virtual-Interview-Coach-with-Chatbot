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