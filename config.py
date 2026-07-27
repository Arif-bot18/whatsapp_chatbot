from dotenv import load_dotenv 
import os
from supabase import Client , create_client

load_dotenv()

META_TOKEN = os.getenv("access_code")
PHONE_NUMBER_ID = os.getenv("phone_numberID")
OWNER_NUMBER = os.getenv("owner_number")
VERSION = "v25.0"

SUPABASE_URL = os.getenv("supabaseurl")
SUPABASE_KEY = os.getenv("supabasekey")

# Initialize Supabase Client once for the entire project
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)