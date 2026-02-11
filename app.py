import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, session, redirect
from flask_session import Session
from groq import Groq
from dotenv import load_dotenv
import difflib
from salesforce_api import (
    get_employee_products,
    get_learning_materials,
    get_certification_vouchers,
    USER_ID,
    # find_product_description,
    save_chat_history
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
app.config["SESSION_FILE_DIR"] = os.getenv("SESSION_FILE_DIR", "./flask_session")
app.config["SESSION_COOKIE_NAME"] = os.getenv("SESSION_COOKIE_NAME", "learning_agent_session")
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "None")
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "True").lower() == "true"
app.config["SESSION_COOKIE_HTTPONLY"] = True
try:
    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
except Exception:
    pass

Session(app)

# -----------------------------------
# Groq Client
# -----------------------------------
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

PRODUCT_DESCRIPTIONS = {}

PRODUCT_ALIASES = {
    "salesforce administrator": "salesforce admin",
    "administrator": "salesforce admin",
    "flow and automation": "flow & automation",
    "flow automation": "flow & automation",
    "salesforce automation": "flow & automation",
    "salesforce flow automation": "flow & automation"
}

# -----------------------------------
# Helper Functions
# -----------------------------------
def is_greeting(text):
    return text.lower().strip() in ["hi", "hello", "hey", "good morning", "good evening"]

def detect_intent(question):
    q = question.lower()
    if "voucher" in q or "certification" in q or "exam" in q:
        return "voucher"
    if "learning" in q or "material" in q or "course" in q or "training" in q or "trailhead" in q:
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

def match_items(items, name_fn, keywords):
    names = [name_fn(i).lower() for i in items]
    sub = []
    for i, n in enumerate(names):
        if any(k in n for k in keywords):
            sub.append(items[i])
    if sub:
        return sub
    phrase = " ".join(keywords).strip()
    if phrase:
        matches = difflib.get_close_matches(phrase, names, n=3, cutoff=0.6)
        if matches:
            picked = []
            setm = set(matches)
            for i, n in enumerate(names):
                if n in setm:
                    picked.append(items[i])
            return picked
    return []

def normalize_product_name(name):
    s = name.lower().strip()
    s = s.replace(" and ", " & ")
    return PRODUCT_ALIASES.get(s, s)

def get_product_description(product_name, learning):

    product_name = product_name.strip().lower()

    for record in learning:
        product_field = record.get("Product_Name__c")

        if product_field:
            db_product = product_field.strip().lower()

            # Exact match OR contains match
            if product_name == db_product or product_name in db_product:
                description = record.get("Description__c")
                if description:
                    return description

    return "No description available for this product."



def find_best_product(products, query):
    q = normalize_product_name(re.sub(r"[^a-z0-9 &]+", " ", query.lower()).strip())
    norm_map = {normalize_product_name(p): p for p in products}
    if q in norm_map:
        return norm_map[q]
    names = list(norm_map.keys())
    close = difflib.get_close_matches(q, names, n=1, cutoff=0.7)
    if close:
        return norm_map[close[0]]
    words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 2]
    candidates = match_items(products, lambda p: p, words) if words else []
    if candidates:
        scores = [(p, difflib.SequenceMatcher(None, q, normalize_product_name(p)).ratio()) for p in candidates]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]
    return None

# -----------------------------------
# Email Sender
# -----------------------------------
def send_voucher_email(name, certification_name, expiry_date):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("ADMIN_EMAIL", "varshinisellamuthu3004@gmail.com")
    timeout = float(os.getenv("EMAIL_SMTP_TIMEOUT", "20"))
    provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()

    body = f"""Certification Voucher Request

Name: {name}
Certification Name: {certification_name}
Expiry Date: {expiry_date}

Submitted via Salesforce Learning Agent.
"""

    try:
        if provider == "sendgrid":
            api_key = os.getenv("SENDGRID_API_KEY")
            if not api_key or not sender or not receiver:
                print("❌ SendGrid credentials missing")
                raise Exception("missing sendgrid config")
            try:
                from sendgrid import SendGridAPIClient
                from sendgrid.helpers.mail import Mail
            except Exception as ie:
                print("❌ SendGrid library not available:", ie)
                raise
            message = Mail(
                from_email=sender,
                to_emails=receiver,
                subject="Certification Voucher Request",
                plain_text_content=body
            )
            sg = SendGridAPIClient(api_key)
            sg.send(message)
            print("✅ Email sent successfully (SendGrid)")
            return "sent"
        else:
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
# -----------------------------------
# AI Response Generator
# -----------------------------------
def groq_answer(question, chat_history, products, learning, vouchers):

    if is_greeting(question):
        return "HOW CAN I ASSIST YOU?"

    # -----------------------------------
    # SKILL LEVEL FOLLOW-UP HANDLING
    # -----------------------------------
    if chat_history:
        last_bot_message = chat_history[-1].get("answer", "")
        if "What is your skill level?" in last_bot_message:
            skill_levels = ["beginner", "intermediate", "advanced"]
            user_skill = next((s for s in skill_levels if s in question.lower()), None)

            if user_skill:
                filtered_learning = [
                    m for m in learning
                    if m.get('skill_level', '').lower() == user_skill
                ]

                if not filtered_learning:
                    return f"No {user_skill.capitalize()} learning materials found."

                learning_list = "\n".join([
                    f"- <a href='{m['link']}' target='_blank'>{m['material']}</a> ({m['skill_level']})"
                    for m in filtered_learning
                ])

                return f"Here are the {user_skill.capitalize()} learning materials:\n\n{learning_list}"

    intent = detect_intent(question)

    # ==========================================
    # 🔥 UPDATED VOUCHER SECTION (FIXED)
    # ==========================================
    if intent == "voucher":

        # Voucher form trigger
        if any(k in question.lower() for k in ["apply", "request", "form", "submit"]):
            return "VOUCHER_FORM"

        if not vouchers:
            return "You have no available certification vouchers."

        q = question.lower()

        # ✅ DIRECTLY SHOW ALL VOUCHERS
        if any(word in q for word in ["all", "available", "list", "show all", "everything"]):
            voucher_list = "\n".join([
                f"- {v['name']} (Status: {v.get('status','N/A')}, Exp: {v.get('expiry_date','N/A')})"
                for v in vouchers
            ])
            return f"Here are your available certification vouchers:\n\n{voucher_list}"

        # 🔍 Specific voucher search
        words = re.findall(r"[a-z0-9]+", q)
        stop = {
            "voucher","certification","apply","request","form","submit",
            "use","available","list","show","for","details","info",
            "describe","description","about","exam"
        }

        keywords = [w for w in words if len(w) > 3 and w not in stop]

        filtered = match_items(vouchers, lambda v: v["name"], keywords) if keywords else []

        if filtered:
            if len(filtered) == 1:
                v = filtered[0]
                return (
                    f"{v['name']} — Voucher status: {v.get('status','N/A')}."
                    f" Expires: {v.get('expiry_date','N/A')}."
                )

            voucher_list = "\n".join([
                f"- {v['name']} (Exp: {v.get('expiry_date','N/A')})"
                for v in filtered
            ])

            return f"Matching certification vouchers:\n\n{voucher_list}\n\nPlease specify one."

        # If user just says "show certification vouchers"
        if "voucher" in q or "certification" in q:
            voucher_list = "\n".join([
                f"- {v['name']} (Exp: {v.get('expiry_date','N/A')})"
                for v in vouchers
            ])
            return f"Here are your available certification vouchers:\n\n{voucher_list}"

        return "Which certification voucher are you looking for?"

    # ==========================================
    # LEARNING SECTION (UNCHANGED)
    # ==========================================
    if intent == "learning":

        if not learning:
            return "No learning materials found for your assigned products."

        skill_levels = ["beginner", "intermediate", "advanced"]
        user_skill = next((s for s in skill_levels if s in question.lower()), None)

        if user_skill:
            filtered_learning = [
                m for m in learning
                if m.get('skill_level', '').lower() == user_skill
            ]

            if not filtered_learning:
                return f"No {user_skill.capitalize()} learning materials found."

            learning_list = "\n".join([
                f"- <a href='{m['link']}' target='_blank'>{m['material']}</a> ({m['skill_level']})"
                for m in filtered_learning
            ])

            return f"Here are the {user_skill.capitalize()} learning materials:\n\n{learning_list}"

        return "What is your skill level? (Beginner / Intermediate / Advanced)"

        # ==========================================
    # 🔥 UPDATED PRODUCT SECTION
    # ==========================================
    if intent == "product":

        if not products:
            return "You have no assigned products."

        q = question.lower()

        desc_markers = [
            "describe", "description", "details",
            "tell me about", "what is", "explain",
            "overview", "info"
        ]

        # -----------------------------
        # If asking for description
        # -----------------------------
        if any(marker in q for marker in desc_markers):

            words = re.findall(r"[a-z0-9]+", q)

            stop = {
                "product", "products", "describe", "description",
                "details", "tell", "about", "what", "is",
                "the", "give", "me", "info", "overview", "explain"
            }

            keywords = [w for w in words if w not in stop and len(w) > 2]

            best_product = find_best_product(products, " ".join(keywords))

            if best_product:
                description = get_product_description(best_product, learning)
                return f"📌 {best_product}\n\n{description}"

            return "Which product are you asking about?"

        # -----------------------------
        # Otherwise list products
        # -----------------------------
        product_list = "\n".join([f"- {p}" for p in products])
        return f"Here are your assigned products:\n\n{product_list}"

        
    # ==========================================
    # FALLBACK TO GROQ
    # ==========================================
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

            try:
                save_chat_history(USER_ID, formatted_request, response)
            except Exception:
                pass

            # Continue to normal flow to show the response

        # -------------------------------
        # Normal Chat Input
        # -------------------------------
        question = request.form.get("question", "").strip()
        if question:
            answer = groq_answer(question, session["chat_history"], products, learning, vouchers)
            session["chat_history"].append({"question": question, "answer": answer})
            try:
                save_chat_history(USER_ID, question, answer)
            except Exception:
                pass

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
