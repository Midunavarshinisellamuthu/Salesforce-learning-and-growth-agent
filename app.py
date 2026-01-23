import os
import re
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_session import Session
from groq import Groq
from dotenv import load_dotenv
from salesforce_api import (
    get_employee_products,
    get_learning_materials,
    get_certification_vouchers,
    USER_ID
)

# -----------------------------------
# Load Environment Variables
# -----------------------------------
load_dotenv()

app = Flask(__name__)

# -----------------------------------
# Session Configuration
# -----------------------------------
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "supersecretkey")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_FILE_DIR"] = "./flask_session"

Session(app)

# -----------------------------------
# Groq Client
# -----------------------------------
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# -----------------------------------
# Greeting Detector
# -----------------------------------
def is_greeting(text):
    greetings = ["hi", "hello", "hey", "good morning", "good evening"]
    return text.lower().strip() in greetings

# -----------------------------------
# Intent Detector
# -----------------------------------
def detect_intent(question):
    q = question.lower()

    if "voucher" in q or "certification" in q:
        return "voucher"

    if "learning" in q or "material" in q or "trailhead" in q:
        return "learning"

    if "product" in q or "assigned" in q:
        return "product"

    return "general"

# -----------------------------------
# Follow-up Question Generator
# -----------------------------------
def get_follow_up(intent):
    if intent == "voucher":
        return "Which certification voucher would you like to use next?"

    if intent == "learning":
        return "Which learning material would you like to start with?"

    if intent == "product":
        return "Which product would you like to focus on?"

    return "What would you like to explore next?"

# -----------------------------------
# Response Cleaner
# -----------------------------------
def normalize_response(text):
    if not text:
        return ""

    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    text = text.replace("•", "").replace("👉", "")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

# -----------------------------------
# AI Answer Generator
# -----------------------------------
def groq_answer(question, chat_history, products, learning, vouchers):

    # Greeting only once
    if is_greeting(question) and not session.get("greeted"):
        session["greeted"] = True
        return (
            "Hi! 😊\n"
            "I can help you with:\n"
            "1. Assigned products\n"
            "2. Learning materials\n"
            "3. Certification vouchers\n\n"
            "What would you like to explore?"
        )

    # Last 5 messages as context
    previous_chat = ""
    for chat in chat_history[-5:]:
        previous_chat += f"User: {chat['question']}\nAssistant: {chat['answer']}\n"

    prompt = f"""
You are a Salesforce Learning Assistant.

Rules:
- Do not greet
- Use only given data
- Short sentences
- Numbered points
- No paragraphs
- No markdown symbols

Context:
{previous_chat}

Assigned Products:
{products}

Learning Materials:
{learning}

Certification Vouchers:
{vouchers}

User Question:
{question}

Answer clearly.
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "Salesforce Enterprise Assistant"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=300
    )

    cleaned_answer = normalize_response(response.choices[0].message.content)

    intent = detect_intent(question)
    follow_up = get_follow_up(intent)

    return f"{cleaned_answer}\n\n{follow_up}"

# -----------------------------------
# Main Route
# -----------------------------------
@app.route("/", methods=["GET", "POST"])
def index():

    if "chat_history" not in session:
        session["chat_history"] = []
        session["greeted"] = False

    products = get_employee_products(USER_ID)
    learning = get_learning_materials(USER_ID)
    vouchers = get_certification_vouchers(USER_ID)

    if request.method == "POST":
        question = request.form.get("question", "").strip()

        if question:
            answer = groq_answer(
                question,
                session["chat_history"],
                products,
                learning,
                vouchers
            )

            session["chat_history"].append({
                "question": question,
                "answer": answer
            })

            session.modified = True

    return render_template(
        "index.html",
        products=products,
        learning=learning,
        vouchers=vouchers,
        chat_history=session["chat_history"]
    )

# -----------------------------------
# API Endpoint (Optional)
# -----------------------------------
@app.route("/data")
def get_data():
    return jsonify({
        "products": get_employee_products(USER_ID),
        "learning": get_learning_materials(USER_ID),
        "vouchers": get_certification_vouchers(USER_ID)
    })

# -----------------------------------
# Clear Chat History
# -----------------------------------
@app.route("/clear_history", methods=["POST"])
def clear_history():
    session.clear()
    return redirect("/")

# -----------------------------------
# Run App
# -----------------------------------
if __name__ == "__main__":
    app.run(debug=True)
