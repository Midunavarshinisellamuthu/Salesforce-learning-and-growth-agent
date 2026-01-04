# config.py
import os

# Salesforce credentials (loaded from environment variables)
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD")
SALESFORCE_SECURITY_TOKEN = os.getenv("SALESFORCE_SECURITY_TOKEN")
SALESFORCE_DOMAIN = os.getenv("SALESFORCE_DOMAIN", "login")  # default = production

# API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
