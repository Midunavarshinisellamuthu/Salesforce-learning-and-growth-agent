from simple_salesforce import Salesforce
from dotenv import load_dotenv
import os

load_dotenv()

# 🔐 Salesforce Sandbox Credentials
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD")
SALESFORCE_SECURITY_TOKEN = os.getenv("SALESFORCE_SECURITY_TOKEN")
SALESFORCE_DOMAIN = os.getenv("SALESFORCE_DOMAIN", "test")  # MUST be 'test' for sandbox
USER_ID = os.getenv("USER_ID")  # Salesforce User Id

# 🔌 Connect to Salesforce Sandbox
sf = Salesforce(
    username=SALESFORCE_USERNAME,
    password=SALESFORCE_PASSWORD,
    security_token=SALESFORCE_SECURITY_TOKEN,
    domain=SALESFORCE_DOMAIN
)

# ----------------------------------------------------
# 1️⃣ Fetch Products Assigned to Employee
# Product__c is TEXT (not lookup)
# ----------------------------------------------------
def get_employee_products(user_id):
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
# 2️⃣ Fetch Learning Materials (Picklist Product__c)
# ----------------------------------------------------
def get_learning_materials(user_id):
    try:
        products = get_employee_products(user_id)
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
        return []


# ----------------------------------------------------
# 3️⃣ Fetch Certification Vouchers
# (No Product relation exists)
# ----------------------------------------------------
def get_certification_vouchers(user_id):
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
