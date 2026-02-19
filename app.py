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
# Certification Guidelines (Static Text)
# -----------------------------------
CERTIFICATION_GUIDELINES = """<b>GUIDELINES FOR CERTIFICATION VOUCHERS</b><br>
1️⃣ <b>Check Your Available Vouchers First</b>
Use the chatbot to view only the vouchers assigned to you.<br>
2️⃣ <b>Verify the Expiry Date</b>
Always check the voucher expiry before planning your exam.<br>
3️⃣ <b>Use the Voucher Only for Assigned Certifications</b>
Apply the voucher only for the certification mentioned in your voucher list.<br>
4️⃣ <b>Do Not Share Your Voucher Code</b>
Voucher codes are personal and linked to your user account.<br>
5️⃣ <b>Request Voucher Through the Chatbot Only</b>
Always use the chatbot form to request vouchers (no manual requests).<br>
6️⃣ <b>Apply the Voucher Before It Expires</b>
Expired vouchers cannot be reactivated.<br>
7️⃣ <b>Use Each Voucher Only Once</b>
After using a voucher, it cannot be reused.<br>
8️⃣ <b>Provide Correct Certification Name in Form</b>
Enter the exact certification name shown in the chatbot.<br>
9️⃣ <b>Track Your Request Status</b>
After submission, check whether your voucher request is approved/processed.<br>
🔟 <b>Contact Admin Only If Voucher Is Missing or Expired</b>
Raise issues only when vouchers are not visible or already expired."""


# -----------------------------------
# Helper Functions
# -----------------------------------
def is_greeting(text):
    return text.lower().strip() in ["hi", "hello", "hey", "good morning", "good evening","good afternoon"]

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

# ✅ FIX: Normalize learning data (handles Salesforce __c fields)
def normalize_learning(learning):
    normalized = []
    for m in learning:
        normalized.append({
            "material": m.get("Material_Name__c", m.get("material", "")),
            "product": m.get("Product_Name__c", m.get("product", "")),
            "skill_level": m.get("Skill_Level__c", m.get("skill_level", "")),
            "material_type": m.get("Material_Type__c", m.get("material_type", "")),
            "link": m.get("Link__c", m.get("link", ""))
        })
    return normalized

def get_product_description(product_name, learning):
    product_name = product_name.strip().lower()
    for record in learning:
        product_field = record.get("Product_Name__c") or record.get("product")
        if product_field:
            db_product = product_field.strip().lower()
            if product_name == db_product or product_name in db_product:
                description = record.get("Description__c") or record.get("description")
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
def send_voucher_email(name, certification_name, duration, expiry_date):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("ADMIN_EMAIL", "varshinisellamuthu3004@gmail.com")
    timeout = float(os.getenv("EMAIL_SMTP_TIMEOUT", "20"))
    provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()

    body = f"""Certification Voucher Request

Name: {name}
Certification Name: {certification_name}
Duration: {duration}
Expiry Date: {expiry_date}

Submitted via Salesforce Learning Agent.
"""

    try:
        if provider == "sendgrid":
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            api_key = os.getenv("SENDGRID_API_KEY")
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
        print(f"❌ Email error: {e}")
        try:
            log_file = "email_logs.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*30}\nTO: {receiver}\nFROM: {sender}\nSUBJECT: Certification Voucher Request\n")
                f.write(body)
                f.write(f"\n{'='*30}\n")
            print(f"✅ Email saved locally to {log_file} (Simulation Mode)")
            return "saved"
        except Exception as log_error:
            print(f"❌ Failed to save email log: {log_error}")
            return False

# -----------------------------------
# AI Response Generator
# -----------------------------------
def groq_answer(question, chat_history, products, learning, vouchers):

    if is_greeting(question):
        return "HOW CAN I ASSIST YOU?"

    # ✅ FIX: Remember context from previous learning prompt
    if chat_history and "What is your skill level?" in chat_history[-1].get("answer", ""):
        intent = "learning"
    else:
        intent = detect_intent(question)

             # ==========================================
    # VOUCHER SECTION (FINAL — SHOWS ONLY GUIDELINES WHEN "CERTIFICATIONS" CLICKED)
    # ==========================================
    if intent == "voucher":

        q_lower = question.strip().lower()

        # ✅ If user clicked or typed "certification" or "certifications"
        #    and did NOT ask about vouchers, forms, or requests → show only guidelines
        if (
            ("certification" in q_lower or "certifications" in q_lower)
            and not any(word in q_lower for word in ["voucher", "apply", "request", "form", "submit", "list", "available", "show"])
        ):
            return CERTIFICATION_GUIDELINES

        # 🔽 Otherwise, continue with normal voucher logic
        if any(k in q_lower for k in ["apply", "request", "form", "submit"]):
            return "VOUCHER_FORM"

        if not vouchers:
            return "You have no available certification vouchers."

        if any(word in q_lower for word in ["all", "available", "list", "show all", "everything"]):
            voucher_list = "\n".join([
                f"- {v['name']} (Status: {v.get('status','N/A')}, Exp: {v.get('expiry_date','N/A')})"
                for v in vouchers
            ])
            return f"Here are your available certification vouchers:\n\n{voucher_list}"

        words = re.findall(r"[a-z0-9]+", q_lower)
        stop = {
            "voucher", "certification", "apply", "request", "form", "submit",
            "use", "available", "list", "show", "for", "details", "info",
            "describe", "description", "about", "exam"
        }

        keywords = [w for w in words if len(w) > 3 and w not in stop]
        filtered = match_items(vouchers, lambda v: v["name"], keywords) if keywords else []

        if filtered:
            if len(filtered) == 1:
                v = filtered[0]
                return (
                    f"{v['name']} — Voucher status: {v.get('status','N/A')}. "
                    f"Expires: {v.get('expiry_date','N/A')}."
                )

            voucher_list = "\n".join([
                f"- {v['name']} (Exp: {v.get('expiry_date','N/A')})"
                for v in filtered
            ])
            return f"Matching certification vouchers:\n\n{voucher_list}\n\nPlease specify one."

        if "voucher" in q_lower or "certification" in q_lower:
            voucher_list = "\n".join([
                f"- {v['name']} (Exp: {v.get('expiry_date','N/A')})"
                for v in vouchers
            ])
            return f"Here are your available certification vouchers:\n\n{voucher_list}"

        return "Which certification voucher are you looking for?"




   # ==========================================
# LEARNING SECTION (FINAL FIXED VERSION)
# ==========================================
    if intent == "learning":
        if not learning:
            return "No learning materials found for your assigned products."

        skill_levels = ["beginner", "intermediate", "advanced"]
        user_skill = next((s for s in skill_levels if s in question.lower()), None)

        words = re.findall(r"[a-z0-9]+", question.lower())

        stop_words = {
            "learning", "material", "materials", "course", "courses",
            "training", "show", "me", "give", "about", "on", "for", "in",
            "along", "which", "level", "beginner", "intermediate", "advanced"
        }

        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        query = " ".join(keywords).strip()

        # Ask for skill level if not provided
        if not user_skill:
            return (
                "What is your skill level? (Beginner / Intermediate / Advanced)\n"
                "Along which learning material do you want?"
            )

        matched_by_name = []
        if query:
            for m in learning:
                material_name = m.get("material", "").lower()
                if all(word in material_name for word in keywords):
                    matched_by_name.append(m)

            # ✅ Fuzzy matching fallback
            if not matched_by_name and query:
                matches = difflib.get_close_matches(
                    query, [m.get("material", "").lower() for m in learning],
                    n=1, cutoff=0.6
                )
                if matches:
                    matched_by_name = [
                        m for m in learning
                        if m.get("material", "").lower() == matches[0]
                    ]

            # ❌ No matching material found at all
            if not matched_by_name:
                return f"No learning materials found for '{query}'."

                                    # 🎯 Exact skill match check
            exact_skill_match = [
                m for m in matched_by_name
                if m.get("skill_level", "").lower() == user_skill
            ]

            # 🚫 If requested level not available → show available levels instead of description
            if not exact_skill_match:
                # Find all available levels for the same material name
                available_levels = sorted({
                    m.get("skill_level", "").capitalize()
                    for m in learning
                    if m.get("material", "").lower() == matched_by_name[0].get("material", "").lower()
                    and m.get("skill_level")
                })

                if not available_levels:
                    return (
                        f"❌ '{query.title()}' is not available in "
                        f"{user_skill.capitalize()} level, and no other skill levels were found."
                    )

                available_str = ", ".join(available_levels)
                return (
                    f"❌ <b>{query.title()}</b> is not available in "
                    f"<b>{user_skill.capitalize()}</b> level.<br><br>"
                    f"✅ Available only in: <b>{available_str}</b> level."
                )

            # ✅ If available in the requested skill level → show info
            m = exact_skill_match[0]
            return (
                f"📘 <b>{m['material']}</b><br><br>"
                f"<b>Product:</b> {m.get('product')}<br>"
                f"<b>Skill Level:</b> {m.get('skill_level')}<br>"
                f"<b>Type:</b> {m.get('material_type')}<br>"
                f"<b>Link:</b> "
                f"<a href='{m.get('link')}' target='_blank' "
                f"style='color:#007bff;text-decoration:none;'>Open Resource</a>"
            )



        # 🟢 Only skill level given → list all materials for that level
        filtered_learning = [
            m for m in learning
            if m.get("skill_level", "").lower() == user_skill
        ]

        if not filtered_learning:
            return f"No {user_skill.capitalize()} learning materials found."

        # ✅ Clickable links for material list
        learning_list = "<br>".join([
            f"- <b>{m['material']}</b> ({m.get('skill_level')}) → "
            f"<a href='{m.get('link')}' target='_blank' "
            f"style='color:#007bff;text-decoration:none;'>Open Resource</a>"
            for m in filtered_learning
        ])

        return (
            f"Here are the {user_skill.capitalize()} learning materials:<br><br>"
            f"{learning_list}<br><br>"
            f"Tell me which one you want details about."
        )


    # ==========================================
    # PRODUCT SECTION
    # ==========================================
    if intent == "product":
        if not products:
            return "You have no assigned products."
        q = question.lower()
        desc_markers = ["describe", "description", "details", "tell me about", "what is", "explain", "overview", "info"]
        if any(marker in q for marker in desc_markers):
            words = re.findall(r"[a-z0-9]+", q)
            stop = {"product","products","describe","description","details","tell","about","what","is","the","give","me","info","overview","explain"}
            keywords = [w for w in words if w not in stop and len(w) > 2]
            best_product = find_best_product(products, " ".join(keywords))
            if best_product:
                description = get_product_description(best_product, learning)
                return f"📌 {best_product}\n\n{description}"
            return "Which product are you asking about?"
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
    learning = normalize_learning(get_learning_materials(USER_ID))  # ✅ FIX: Normalize here
    vouchers = get_certification_vouchers(USER_ID)

    if request.method == "POST":
        if "certification_name" in request.form:
            name = request.form.get("name", "").strip()
            certification_name = request.form.get("certification_name", "").strip()
            duration = request.form.get("duration", "").strip()
            selected_voucher = next((v for v in vouchers if certification_name.lower() in v["name"].lower()), None)
            if not selected_voucher:
                response = f"❌ The certification '{certification_name}' is NOT available in your assigned vouchers.\nPlease check your available certifications and try again."
            else:
                expiry_date = selected_voucher.get("expiry_date", "N/A")
                email_status = send_voucher_email(name, certification_name, duration, expiry_date)
                if email_status == "sent":
                    response = f"✅ The certification '{certification_name}' is available.\nYour voucher request has been submitted successfully.\n📧 Email notification sent."
                elif email_status == "saved":
                    response = f"✅ The certification '{certification_name}' is available.\nYour voucher request has been submitted successfully.\n⚠️ Email saved to logs (Network Unavailable)."
                else:
                    response = f"✅ The certification '{certification_name}' is available.\n⚠️ Email service is currently unavailable.\nPlease try again later."
            formatted_request = f"📋 Voucher Request Submitted\n👤 Name: {name}\n🎓 Certification: {certification_name}"
            session["chat_history"].append({"question": formatted_request, "answer": response})
            try:
                save_chat_history(USER_ID, formatted_request, response)
            except Exception:
                pass

        question = request.form.get("question", "").strip()
        if question:
            answer = groq_answer(question, session["chat_history"], products, learning, vouchers)
            session["chat_history"].append({"question": question, "answer": answer})
            try:
                save_chat_history(USER_ID, question, answer)
            except Exception:
                pass

    return render_template("index.html", products=products, learning=learning, vouchers=vouchers, chat_history=session["chat_history"])

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
