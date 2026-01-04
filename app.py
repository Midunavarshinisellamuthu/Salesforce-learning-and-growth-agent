import os
from flask import Flask, render_template, request, session, redirect, jsonify
from groq import Groq
from dotenv import load_dotenv
from salesforce_api import (
    get_employee_products,
    get_learning_materials,
    get_certification_vouchers,
    USER_ID
)
from difflib import get_close_matches

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")

# 🔹 Groq Client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ----------------------------------------------------
# Utility: Match Product Name from Question
# ----------------------------------------------------
def find_best_match(question, products):
    if not products:
        return None
    matches = get_close_matches(
        question.lower(),
        [p.lower() for p in products],
        n=1,
        cutoff=0.4
    )
    if matches:
        for p in products:
            if p.lower() == matches[0]:
                return p
    return None


# ----------------------------------------------------
# Groq AI Answer Generator (Prompt-based)
# ----------------------------------------------------
def groq_answer(question, chat_history, products, learning, vouchers):

    previous_chat = ""
    for chat in chat_history[-10:]:
        previous_chat += f"User: {chat['question']}\nAI: {chat['answer']}\n"

    prompt = f"""
You are an AI-powered Salesforce Learning & Growth Assistant.

Previous Conversation:
{previous_chat}

Employee Assigned Products:
{products}

Learning Materials:
{learning}

Certification Vouchers:
{vouchers}

User Question:
{question}

Rules:
- Answer ONLY the user's question
- Be concise and clear
- Use learning materials if relevant
- Mention product name only if applicable
- Do NOT hallucinate data
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You are a helpful Salesforce assistant"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=300
    )

    return response.choices[0].message.content


# ----------------------------------------------------
# Main Chat Route
# ----------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():

    if "chat_history" not in session:
        session["chat_history"] = []

    answer = ""

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
        answer=answer,
        products=products,
        learning=learning,
        vouchers=vouchers,
        chat_history=session["chat_history"]
    )


# ----------------------------------------------------
# API: Raw Salesforce Data
# ----------------------------------------------------
@app.route("/data", methods=["GET"])
def get_data():
    return jsonify({
        "products": get_employee_products(USER_ID),
        "learning": get_learning_materials(USER_ID),
        "vouchers": get_certification_vouchers(USER_ID)
    })


# ----------------------------------------------------
# Clear Chat History
# ----------------------------------------------------
@app.route("/clear_history", methods=["POST"])
def clear_history():
    session.pop("chat_history", None)
    return redirect("/")


# ----------------------------------------------------
# Run App
# ----------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
