import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, session, redirect
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
# Helper Functions
# -----------------------------------
def is_greeting(text):
    return text.lower().strip() in ["hi", "hello", "hey", "good morning", "good evening"]

def detect_intent(question):
    q = question.lower()
    if "voucher" in q or "certification" in q:
        return "voucher"
    if "learning" in q or "material" in q:
        return "learning"
    if "product" in q:
        return "product"
    return "general"

def normalize_response(text):
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

# -----------------------------------
# Email Sender
# -----------------------------------
def send_voucher_email(name, certification_name, expiry_date):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("ADMIN_EMAIL", "varshinisellamuthu3004@gmail.com")
    timeout = float(os.getenv("EMAIL_SMTP_TIMEOUT", "20"))

    body = f"""Certification Voucher Request

Name: {name}
Certification Name: {certification_name}
Expiry Date: {expiry_date}

Submitted via Salesforce Learning Agent.
"""

    try:
        if not sender or not password:
            print("❌ Email credentials missing")
            return False

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = "Certification Voucher Request"

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=timeout)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
        server.quit()

        print("✅ Email sent successfully")
        return "sent"

    except Exception as e:
        error_msg = str(e)
        if "10060" in error_msg or "timed out" in error_msg.lower():
            print("⚠️ Network blocked email connection (Timeout). Switching to OFFLINE MODE.")
        else:
            print(f"❌ Email error: {error_msg}")
            print("⚠️ Switching to OFFLINE MODE.")
        
        # Fallback: Save email to a local file for verification
        try:
            log_file = "email_logs.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*30}\n")
                f.write(f"TO: {receiver}\n")
                f.write(f"FROM: {sender}\n")
                f.write(f"SUBJECT: Certification Voucher Request\n")
                f.write(f"{'-'*30}\n")
                f.write(body)
                f.write(f"{'='*30}\n")
            
            print(f"✅ Email saved locally to {log_file} (Simulation Mode)")
            return "saved"  # Return "saved" so the UI shows success
        except Exception as log_error:
            print(f"❌ Failed to save email log: {log_error}")
            return False

# -----------------------------------
# AI Response Generator
# -----------------------------------
def groq_answer(question, chat_history, products, learning, vouchers):

    if is_greeting(question):
        return "HOW CAN I ASSIST YOU?"

    # Check if the previous message was asking for skill level
    if chat_history:
        last_bot_message = chat_history[-1].get("answer", "")
        if "What is your skill level?" in last_bot_message:
            skill_levels = ["beginner", "intermediate", "advanced"]
            user_skill = next((s for s in skill_levels if s in question.lower()), None)
            
            if user_skill:
                filtered_learning = [m for m in learning if m.get('skill_level', '').lower() == user_skill]
                if not filtered_learning:
                    return f"No {user_skill.capitalize()} learning materials found."
                
                learning_list = "\n".join([f"- <a href='{m['link']}' target='_blank'>{m['material']}</a> ({m['skill_level']})" for m in filtered_learning])
                return f"Here are the {user_skill.capitalize()} learning materials:\n\n{learning_list}"
            else:
                 # If user replied something else, maybe we should fall through or repeat the question?
                 # Let's assume if they didn't provide a valid skill, we treat it as a new intent or general question.
                 pass

    intent = detect_intent(question)

    if intent == "voucher" and any(k in question.lower() for k in ["apply", "request", "form", "submit"]):
        return "VOUCHER_FORM"

    if intent == "voucher":
        if not vouchers:
            return "You have no available certification vouchers."
        q = question.lower()
        words = re.findall(r"[a-z0-9]+", q)
        stop = {"voucher","certification","apply","request","form","submit","use","available","list","show","for","details","info","describe","description","about"}
        if "product" in q:
            voucher_list = "\n".join([f"- {v['name']} (Exp: {v.get('expiry_date', 'N/A')})" for v in vouchers])
            return f"Certification vouchers are not product-specific.\n\nAvailable vouchers:\n\n{voucher_list}\n\nPlease specify the certification name."
        keywords = [w for w in words if len(w) > 3 and w not in stop]
        filtered = [v for v in vouchers if any(k in v["name"].lower() for k in keywords)] if keywords else []
        if filtered:
            if len(filtered) == 1:
                v = filtered[0]
                name = v["name"]
                status = v.get("status", "N/A")
                expiry = v.get("expiry_date", "N/A")
                return f"{name}\nStatus: {status}\nExpiry: {expiry}"
            voucher_list = "\n".join([f"- {v['name']} (Exp: {v.get('expiry_date', 'N/A')})" for v in filtered])
            return f"Matching certification vouchers:\n\n{voucher_list}\n\nPlease specify one."
        return "Which certification voucher are you looking for?"

    if intent == "learning":
        if not learning:
            return "No learning materials found for your assigned products."
        
        # Check if the user has already provided a skill level in the current message
        skill_levels = ["beginner", "intermediate", "advanced"]
        user_skill = next((s for s in skill_levels if s in question.lower()), None)
        
        q = question.lower()
        desc_markers = ["describe","description","details","detail","info","information","what is","what are","tell me about"]
        if any(m in q for m in desc_markers):
            words = re.findall(r"[a-z0-9]+", q)
            stop = {"learning","material","materials","describe","description","details","detail","info","information","about","tell","show","give","for","the","my"}
            keywords = [w for w in words if len(w) > 2 and w not in stop]
            filtered = [m for m in learning if any(k in m["material"].lower() for k in keywords)] if keywords else []
            if filtered:
                if len(filtered) == 1:
                    m = filtered[0]
                    mat = m.get("material", "N/A")
                    mtype = m.get("material_type", "N/A")
                    skill = m.get("skill_level", "N/A")
                    link = m.get("link") or "N/A"
                    return f"{mat}\nType: {mtype}\nSkill: {skill}\nLink: {link}"
                learning_list = "\n".join([f"- {m['material']}" for m in filtered])
                return f"Matching learning materials:\n\n{learning_list}\n\nPlease specify one."
            return "Which learning material are you asking about?"
        
        # If no skill level provided, check if we asked for it in the last message
        if not user_skill and chat_history:
            last_bot_message = chat_history[-1].get("answer", "")
            if "What is your skill level?" in last_bot_message:
                 # The user's current message (question) might be the skill level answer (e.g., "Beginner")
                 # We already checked question.lower() for skill levels above, but maybe they just typed "Beginner" without "learning" keyword?
                 # Actually, if intent is "learning", it detected "learning" or "material" in the question.
                 # If the user just replied "Beginner", intent might be "general" (default).
                 pass
        
        if user_skill:
             filtered_learning = [m for m in learning if m.get('skill_level', '').lower() == user_skill]
             if not filtered_learning:
                 return f"No {user_skill.capitalize()} learning materials found."
             
             learning_list = "\n".join([f"- <a href='{m['link']}' target='_blank'>{m['material']}</a> ({m['skill_level']})" for m in filtered_learning])
             return f"Here are the {user_skill.capitalize()} learning materials:\n\n{learning_list}"

        return "What is your skill level? (Beginner / Intermediate / Advanced)"

    if intent == "product":
        if not products:
            return "You have no assigned products."
        
        q = question.lower()
        desc_markers = ["describe","description","details","detail","info","information","what is","what are","tell me about"]
        if any(m in q for m in desc_markers):
            words = re.findall(r"[a-z0-9]+", q)
            stop = {"product","products","describe","description","details","detail","info","information","about","tell","show","give","for","the","my","assigned"}
            keywords = [w for w in words if len(w) > 2 and w not in stop]
            filtered = [p for p in products if any(k in p.lower() for k in keywords)] if keywords else []
            if filtered:
                if len(filtered) == 1:
                    p = filtered[0]
                    prompt = f"Provide a concise 2-3 sentence description of the product '{p}'. If you are not certain, say 'No specific description available.' Only plain text."
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=120
                    )
                    return normalize_response(response.choices[0].message.content)
                product_list = "\n".join([f"- {pi}" for pi in filtered])
                return f"Matching products:\n\n{product_list}\n\nPlease specify one."
            return "Which product are you asking about?"
        
        product_list = "\n".join([f"- {p}" for p in products])
        return f"Here are your assigned products:\n\n{product_list}"

    prompt = f"""
Context:
Products: {', '.join(products) if products else 'None'}
Learning Materials: {', '.join([m['material'] for m in learning]) if learning else 'None'}
Vouchers: {', '.join([v['name'] for v in vouchers]) if vouchers else 'None'}

User question: {question}
Use short and clear answers.
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=200
    )

    return normalize_response(response.choices[0].message.content)

# -----------------------------------
# Main Route
# -----------------------------------
@app.route("/", methods=["GET", "POST"])
def index():

    session.setdefault("chat_history", [])

    products = get_employee_products(USER_ID)
    learning = get_learning_materials(USER_ID)
    vouchers = get_certification_vouchers(USER_ID)

    if request.method == "POST":

        # -------------------------------
        # Voucher Form Submission
        # -------------------------------
        if "certification_name" in request.form:
            name = request.form.get("name", "").strip()
            certification_name = request.form.get("certification_name", "").strip()

            # Find matching voucher
            selected_voucher = next(
                (v for v in vouchers if certification_name.lower() in v["name"].lower()), 
                None
            )

            if not selected_voucher:
                response = (
                    f"❌ The certification '{certification_name}' is NOT available in your assigned vouchers.\n"
                    "Please check your available certifications and try again."
                )
            else:
                expiry_date = selected_voucher.get("expiry_date", "N/A")
                email_status = send_voucher_email(name, certification_name, expiry_date)

                if email_status == "sent":
                    response = (
                        f"✅ The certification '{certification_name}' is available.\n"
                        "Your voucher request has been submitted successfully.\n"
                        "📧 Email notification sent."
                    )
                elif email_status == "saved":
                    response = (
                        f"✅ The certification '{certification_name}' is available.\n"
                        "Your voucher request has been submitted successfully.\n"
                        "⚠️ Email saved to logs (Network Unavailable)."
                    )
                else:
                    response = (
                        f"✅ The certification '{certification_name}' is available.\n"
                        "⚠️ Email service is currently unavailable.\n"
                        "Please try again later."
                    )

            # Add both user question and AI response to chat history
            formatted_request = (
                "📋 Voucher Request Submitted\n"
                f"👤 Name: {name}\n"
                f"🎓 Certification: {certification_name}"
            )
            session["chat_history"].append({
                "question": formatted_request,
                "answer": response
            })

            # Continue to normal flow to show the response

        # -------------------------------
        # Normal Chat Input
        # -------------------------------
        question = request.form.get("question", "").strip()
        if question:
            answer = groq_answer(question, session["chat_history"], products, learning, vouchers)
            session["chat_history"].append({"question": question, "answer": answer})

    return render_template(
        "index.html",
        products=products,
        learning=learning,
        vouchers=vouchers,
        chat_history=session["chat_history"]
    )

# -----------------------------------
# Clear Chat
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
