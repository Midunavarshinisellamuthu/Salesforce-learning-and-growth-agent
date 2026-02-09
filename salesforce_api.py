from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os
import json

load_dotenv()

# 🔐 Salesforce Sandbox Credentials
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD")
SALESFORCE_SECURITY_TOKEN = os.getenv("SALESFORCE_SECURITY_TOKEN")
SALESFORCE_DOMAIN = os.getenv("SALESFORCE_DOMAIN", "test")
USER_ID = os.getenv("USER_ID")
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"
HTTP_PROXY = os.getenv("HTTP_PROXY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")
_proxies = {}
if HTTP_PROXY:
    _proxies["http"] = HTTP_PROXY
if HTTPS_PROXY:
    _proxies["https"] = HTTPS_PROXY

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
    except Exception:
        sf = None

def _offline_products():
    v = os.getenv("OFFLINE_PRODUCTS")
    if v:
        try:
            return json.loads(v)
        except Exception:
            pass
    return ["Flow & Automation", "People Portal", "Salesforce Admin"]

def _offline_learning(products):
    v = os.getenv("OFFLINE_LEARNING")
    if v:
        try:
            return json.loads(v)
        except Exception:
            pass
    return [
        {"material": "Admin Trailhead", "product": "Salesforce Admin", "link": "https://trailhead.salesforce.com", "skill_level": "Beginner", "material_type": "Trail"},
        {"material": "Flow Best Practices", "product": "Flow & Automation", "link": "https://trailhead.salesforce.com", "skill_level": "Intermediate", "material_type": "Guide"},
        {"material": "People Portal Overview", "product": "People Portal", "link": "https://example.com/people-portal", "skill_level": "Beginner", "material_type": "Doc"}
    ]

def _offline_vouchers():
    v = os.getenv("OFFLINE_VOUCHERS")
    if v:
        try:
            return json.loads(v)
        except Exception:
            pass
    return [
        {"name": "Salesforce Administrator Certification Voucher", "status": "Available", "voucher_code": "ADM-XXXX", "expiry_date": "2026-04-30"},
        {"name": "Flow & Automation Certification Voucher", "status": "Available", "voucher_code": "FLOW-YYYY", "expiry_date": "2025-12-31"}
    ]

# ----------------------------------------------------
# 1️⃣ Fetch Products Assigned to Employee
# Product__c is TEXT (not lookup)
# ----------------------------------------------------
def get_employee_products(user_id):
    if OFFLINE_MODE or sf is None:
        return _offline_products()
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
        return _offline_products()


# ----------------------------------------------------
# 2️⃣ Fetch Learning Materials (Picklist Product__c)
# ----------------------------------------------------
def get_learning_materials(user_id):
    products = get_employee_products(user_id)
    if OFFLINE_MODE or sf is None:
        return _offline_learning(products)
    try:
        if not products:
            return []
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
        return _offline_learning(products)


# ----------------------------------------------------
# 3️⃣ Fetch Certification Vouchers
# (No Product relation exists)
# ----------------------------------------------------
def get_certification_vouchers(user_id):
    if OFFLINE_MODE or sf is None:
        return _offline_vouchers()
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
        return _offline_vouchers()
