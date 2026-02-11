from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os
import json

load_dotenv()

# 🔐 Salesforce Credentials
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD")
SALESFORCE_SECURITY_TOKEN = os.getenv("SALESFORCE_SECURITY_TOKEN")
SALESFORCE_DOMAIN = os.getenv("SALESFORCE_DOMAIN", "test")

# 🔹 User & Mode
USER_ID = os.getenv("USER_ID")
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"

# 🔹 Proxy (Optional)
HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

# 🔹 Chat History Configuration (IMPORTANT)
CHAT_HISTORY_OBJECT = os.getenv("CHAT_HISTORY_OBJECT", "Chat_history__c")
CHAT_HISTORY_EMPLOYEE_FIELD = os.getenv("CHAT_HISTORY_EMPLOYEE_FIELD", "Employee_user__c")
CHAT_HISTORY_QUESTION_FIELD = os.getenv("CHAT_HISTORY_QUESTION_FIELD", "Question__c")
CHAT_HISTORY_ANSWER_FIELD = os.getenv("CHAT_HISTORY_ANSWER_FIELD", "Answer__c")

# ----------------------------------------------------
# 🔌 Proxy Setup
# ----------------------------------------------------
_proxies = {}
if HTTP_PROXY:
    _proxies["http"] = HTTP_PROXY
if HTTPS_PROXY:
    _proxies["https"] = HTTPS_PROXY

# ----------------------------------------------------
# 🔗 Salesforce Connection
# ----------------------------------------------------
sf = None
if not OFFLINE_MODE and SALESFORCE_USERNAME and SALESFORCE_PASSWORD and SALESFORCE_SECURITY_TOKEN:
    try:
        sf = Salesforce(
            username=SALESFORCE_USERNAME,
            password=SALESFORCE_PASSWORD,
            security_token=SALESFORCE_SECURITY_TOKEN,
            domain=SALESFORCE_DOMAIN,
            proxies=_proxies or None
        )
        print("✅ Salesforce connected successfully.")
    except Exception as e:
        print("❌ Salesforce connection failed:", e)
        sf = None


# ----------------------------------------------------
# 1️⃣ Fetch Products Assigned to Employee
# ----------------------------------------------------
def get_employee_products(user_id):
    if OFFLINE_MODE or sf is None:
        return []
    try:
        query = f"""
            SELECT Product__c
            FROM Product_Assignment__c
            WHERE Employee__c = '{user_id}'
        """
        records = sf.query_all(query)["records"]
        return [r["Product__c"] for r in records if r.get("Product__c")]
    except Exception as e:
        print("❌ get_employee_products error:", e)
        return []


# ----------------------------------------------------
# 2️⃣ Fetch Learning Materials
# ----------------------------------------------------
def get_learning_materials(user_id):
    products = get_employee_products(user_id)

    if OFFLINE_MODE or sf is None or not products:
        return []

    try:
        product_filter = ",".join([f"'{p}'" for p in products])
        query = f"""
            SELECT Name, Product__c, Link__c, Skill_Level__c, Material_Type__c
            FROM Learning_Material__c
            WHERE Product__c IN ({product_filter})
        """
        records = sf.query_all(query)["records"]

        return [
            {
                "material": r["Name"],
                "product": r["Product__c"],
                "link": r.get("Link__c"),
                "skill_level": r.get("Skill_Level__c"),
                "material_type": r.get("Material_Type__c")
            }
            for r in records
        ]
    except Exception as e:
        print("❌ get_learning_materials error:", e)
        return []


# ----------------------------------------------------
# 3️⃣ Fetch Certification Vouchers
# ----------------------------------------------------
def get_certification_vouchers(user_id):
    if OFFLINE_MODE or sf is None:
        return []

    try:
        query = f"""
            SELECT Name, Status__c, VoucherCode__c, Expiry_Date__c
            FROM Certification_Voucher__c
            WHERE Employee__c = '{user_id}'
        """
        records = sf.query_all(query)["records"]

        return [
            {
                "name": r["Name"],
                "status": r.get("Status__c"),
                "voucher_code": r.get("VoucherCode__c"),
                "expiry_date": r.get("Expiry_Date__c")
            }
            for r in records
        ]
    except Exception as e:
        print("❌ get_certification_vouchers error:", e)
        return []


# ----------------------------------------------------
# 4️⃣ Save Chat History (SAFE VERSION)
# ----------------------------------------------------
def save_chat_history(user_id: str, question: str, answer: str) -> bool:
    if OFFLINE_MODE or sf is None:
        print("⚠️ Offline mode or Salesforce not connected.")
        return False

    try:
        payload = {
            CHAT_HISTORY_QUESTION_FIELD: question,
            CHAT_HISTORY_ANSWER_FIELD: answer
        }

        # Add Employee field only if configured
        if CHAT_HISTORY_EMPLOYEE_FIELD and user_id:
            payload[CHAT_HISTORY_EMPLOYEE_FIELD] = user_id

        print("📤 Saving Chat History:", payload)

        getattr(sf, CHAT_HISTORY_OBJECT).create(payload)

        print("✅ Chat history saved successfully.")
        return True

    except Exception as e:
        print("❌ save_chat_history error:", e)
        return False
