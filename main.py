
from fastapi import FastAPI , Request ,Query,Response,HTTPException,BackgroundTasks
from openai import OpenAI
from pydantic import BaseModel , HttpUrl
from difflib import get_close_matches
from dotenv import load_dotenv
import os , csv , re ,json,datetime,gspread , requests , threading,time
from oauth2client.service_account import ServiceAccountCredentials
import hashlib
import mimetypes
from supabase import Client , create_client
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from services import send_text_message,send_button_message
from config import supabase,META_TOKEN,PHONE_NUMBER_ID,VERSION
from fastapi.staticfiles import StaticFiles
from fastapi import File,UploadFile,Form
from typing import Literal



load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
base_dir = os.path.dirname(os.path.abspath(__file__))
upload_dir = os.path.join(base_dir,"upload")
meta_token = os.getenv("access_code")
os.makedirs(upload_dir,exist_ok =True)
app = FastAPI()
app.mount("/upload",StaticFiles(directory=upload_dir),name="upload")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows any local file layout to connect seamlessly
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
user = {}
processed_msg = {}

client = OpenAI(api_key = os.getenv("GROQ_API_KEY"),base_url="https://api.groq.com/openai/v1")

leads_db = {}
daily_stats = {
    "date":datetime.datetime.now(),
    "total":0,
    "High":0,
    "Medium":0,
    "Low":0,
    "Demo":0
}
def follow_up_checker():
    """
    this function will run in background for follow-ups after 1 hour and 24 hours"""
    while True:
        #now time used to calculate the time
        now = datetime.datetime.now()
        #to get the last_seen
        for number,data in list(user.items()):
            #if last_seen not there then it will return None
            last_seen = data.get("last_seen")
            #continue if None
            if not last_seen:
                continue
            #to know the difference
            diff = (now - last_seen).total_seconds()
            if data.get("intent") =="Low Value":
                print("ider")
                continue

            if data.get("step") == "completed":
                print("mear bhai")
                continue
            #this will execute at 1 hour
            if diff >= 160 and not data.get("followed_1h"):
                data["followed_1h"] = True
                supabase.table("Student").update({"followed_1h":True}).eq("phone_number",number).execute()
                send_button_message(body_text = "Hey 👋 just checking in — would you like to book your demo?",buttons = [{"id":"demo_book","title":"Free Demo Class"}],to_number = number)

            # this will excute after 24 hours
            elif  diff >= 180  and not data.get("followed_24h"):
                data["followed_24h"] = True
                supabase.table("Student").update({"followed_24h":True}).eq("phone_number",number).execute()
                send_button_message(body_text = """Hi 👋\nMany students like you start with a demo class.\nWant me to reserve a slot for you?""",buttons = [{"id":"demo_book","title":"Free Demo Class"}],to_number = number)

        time.sleep(30)
# this will help to run the function in background if main stop this function will also stop
threading.Thread(target = follow_up_checker,daemon = True).start()

def save_to_google_sheets(name,number,requirement,priority,reason):
    try:
        client = gspread.service_account(filename = "creds.json")

        sheet = client.open(os.getenv("FILE_NAME")).sheet1

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp,name,number,requirement,priority,reason]

        sheet.append_row(row)
        print("leads saved to google sheets successfully!")


    except Exception as e:
        print(f"error saving to google sheet:{e}")



def llm_response(user_msg):
    response = client.responses.create(input=f"""
You are a sales assistant for a coaching institute.

Your job is to analyze a user's message and classify the lead based on their intent to join a course.

Classify into ONLY one of these:
- High Value → Ready to join, asking about demo, admission, start date, or showing urgency
- Medium Value → Interested but asking for details like fees, duration, syllabus
- Low Value → Just exploring, vague messages, not serious

Rules:
- If user shows urgency or asks about joining/demo → High Value
- If user asks general info → Medium Value
- If message is unclear, casual, or not serious → Low Value
- Be strict. Do not overestimate.

Return ONLY valid JSON in this format:
{{"priority": "High Value / Medium Value / Low Value", "reason": "short explanation"}}

User message:
{user_msg}

Examples:

Message: "I want to join your course, when does it start?"
Output: {{"priority": "High Value", "reason": "User wants to join and asked start date"}}

Message: "What is the fee for python course?"
Output: {{"priority": "Medium Value", "reason": "User asking for pricing info"}}

Message: "ok"
Output: {{"priority": "Low Value", "reason": "No clear intent"}} """,model = os.getenv("model"))
    return response.output_text


def generate_answer(msg):
    response = client.responses.create(input= f"""
    You are a professional institute counselor chatting with a student on WhatsApp.

    Your job is to:
    - Answer the student's question clearly
    - Keep replies short and natural (2-4 lines max)
    - Sound friendly and human (not robotic)
    - Guide the conversation towards booking a demo class

    Rules:
    - Do NOT return JSON
    - Do NOT explain like a teacher
    - Do NOT give long paragraphs
    - Always keep it conversational

    Behavior:
    - If user asks about fees → give a general range and suggest demo
    - If user asks about timing → say flexible batches and suggest demo
    - If user asks about course → give brief info and suggest demo
    - If unsure → give a safe helpful answer and guide toward demo

    Style:
    - Use simple English
    - Use WhatsApp tone (like 👍 😊 occasionally)
    - Keep it concise

    Goal:
    - Help the student
    - Build trust
    - Gently push towards booking a demo class

    Now respond to the user message accordingly.{msg})""",model = os.getenv("model"))
    return response.output_text


def coaching_classifier(message):

    msg = message.lower()
    if any(word in msg for word in ["demo", "join", "enroll", "admission", "start"]):
        return {
            "priority":"High Value",
            "reason":"high intent of buying"
        }
    elif any(word in msg for word in ["fees", "price", "duration", "timing", "details"]):
        return {
            "priority":"Medium Value",
            "reason":"asking details of the course"
        }
    elif any(word in msg for word in ["ok", "hmm", "later", "just checking"]):
        return {
            "priority":"Low Value",
            "reason":"low intent of buying"
        }

    return None

def normalize_priority(text):
    text = text.lower().strip()
    options = ["high value","medium value","low value"]
    match = get_close_matches(text,options,n=1,cutoff=0.6)
    if  match:
        return match[0].title()

    return "Medium value"

def parser_classifier(message):
    priority = "Medium Value"
    reason = "Could not clearly determine, default applied"

    if isinstance(message, dict):
        message = json.dumps(message)

    if not message or not isinstance(message,str):
        return priority,reason

    message = message.strip()
    message = message.replace("```json","").replace("```","").strip()

    try:
        data = json.loads(message)
        raw_priority = data.get("priority","")
        raw_reason = data.get("reason","")
        if raw_priority:
            priority = normalize_priority(raw_priority)
        if raw_reason:
            reason = raw_reason
    except:
        priority_match = re.search(r'"priority"\s*:\s*"(High Value|Medium Value|Low Value)"', message, re.IGNORECASE) 

        reason_match = re.search(r'"?reason"?\s*:\s*([^"]+)',message,re.IGNORECASE)
        if priority_match:
            priority = normalize_priority(priority_match.group(1))
        if reason_match:
            reason = reason_match.group(1).strip()

    try:

        reason = str(reason).strip()
        reason = re.sub(r'[\n\r\t]+','',reason)
        reason = re.sub(r'\s+',' ',reason)
        reason = reason.strip('"').strip("'")
    except:
        if not reason:
            reason = "No clear reason provided"

    return priority,reason
 


# This is the "Handshake" code Meta needs
@app.get("/webhook")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")) -> Response:

    """ @app when anyone is request the to server this functions has to be execute /webhook is the system which send the data one system to another automatically
    args Query is used to get the data mode:str is hinting alias is to get the value of that variable """
    # This must match EXACTLY what you type in the Meta Dashboard
    MY_VERIFY_TOKEN = os.getenv("verification_code")

    if mode == "subscribe" and token == MY_VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        if not challenge:
            return Response(content = "challenge code is missing",status_code = 400)
        # You MUST return the challenge as plain text
        return Response(content=challenge, media_type="text/plain")
    
    return Response(content="Verification failed", status_code=403)
    
PROCESSED_MESSAGE_IDS = set()

@app.post("/webhook")
async def receive_message(request: Request):
    """ take the user data through Request class and store in request object """
    data = await request.json()
    msg = None
    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return {"status": "ignored"}

        message_obj = value["messages"][0]        
        user_number = message_obj["from"]
        msg_id = message_obj["id"]

        if msg_id in PROCESSED_MESSAGE_IDS:
                print(f"⚠️ Meta Retry Storm Blocked! Dropping Duplicate ID: ({msg_id})")
                return {"status": "ignored_duplicate"}
        
        PROCESSED_MESSAGE_IDS.add(msg_id)
        if len(PROCESSED_MESSAGE_IDS) > 2000:
                PROCESSED_MESSAGE_IDS.pop()
                
        if "text" in message_obj:
            msg = message_obj["text"]["body"]
            print("Text Message:",msg)

        elif "interactive" in message_obj:
            msg  = message_obj["interactive"]["button_reply"]["id"]
            print("Button Clicked",msg)

        supabasequery =supabase.table("Student").select("is_human_handling").eq("phone_number",user_number).execute()

        if msg and user_number:
            current_time_string = datetime.datetime.now(datetime.timezone.utc).isoformat()
            supabase.table("Student").upsert({
                "phone_number": user_number,
                "last_seen": current_time_string,
                "has_unread": True
                    }).execute()
                    # Save the incoming student message to the history logs
            supabase.table("messages").insert({
                    "phone_number": user_number,
                    "sender": "student",
                    "message_text": msg
                    }).execute()

        if supabasequery.data:
            is_human = supabasequery.data[0]["is_human_handling"]

            if is_human == True:
                print(f"Bot is PAUSED for {user_number}. Message ignored by bot.")
                current_time_string = datetime.datetime.now(datetime.timezone.utc).isoformat()

                supabase.table("Student").update({"last_seen":current_time_string}).eq("phone_number",user_number).execute()

                return {"status":"handle by human"}


        whatsapp_message(msg,user_number)

    except Exception as e:
        print(f"Error parsing Meta JSON: {e}")

    return None

def upload_file_to_supabase(supabase_client : Client, local_path :str):
    try:
        filename = os.path.basename(local_path)

        content_type,_ = mimetypes.guess_type(filename)

        if not content_type:
            content_type = "application/octet-stream"

        file_key = f"uploaded_files/{filename}"
        with open(local_path,"rb") as file:
            supabase_client.storage.from_("Institute Media").upload(
                path = file_key,
                file = file,
                file_option = {"content_type":content_type})
        public_url = supabase_client.storage.from_("Institute Media").get_public_url(file_key)
        return public_url
    except Exception as e:
        print(f"Upload failed:{e}")
        return None
    
@app.post("/dashboard/send-media")
async def dashboard_send_media(phone_number:str = Form(...),caption:str = Form(None),file: UploadFile = File(...)):
    try:
        clean_filename =file.filename.replace(" ","_")
        file_path = os.path.join(upload_dir,clean_filename)

        with open(file_path,"wb") as buffer:
            buffer.write(await file.read())

        base_public_Url = os.getenv("PUBLIC_URL")
        media_public_url = f"{base_public_Url}/upload/{clean_filename}"
        print(media_public_url)


        mime_type,_ = mimetypes.guess_type(file_path)
        if mime_type and mime_type.startswith("image/"):
            message_type = "image"
        elif mime_type and mime_type.startswith("video/"):
            message_type = "video"
        else:
            message_type = "document"
        url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type": "application/json"
        }

        base_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": message_type
        }

        if message_type == "image":
            base_payload["image"] = {"link":media_public_url}
            if caption:
                base_payload["image"]["caption"] = caption
        elif message_type == "video":
            base_payload["video"] = {"link":media_public_url}
            if caption:
                base_payload["video"]["caption"] = caption
        else:
            base_payload["document"] = {
                "link":media_public_url,
                "filename": clean_filename
            }
            if caption:
                base_payload["document"]["caption"] = caption

        response = requests.post(url,headers=headers,json=base_payload)
        response_data = response.json()
        if response.status_code == 200:
            current_time_string = datetime.datetime.now(datetime.timezone.utc).isoformat()


            update_data = {"last_seen":current_time_string,"reminder_at": None,"ai_reply_count":0}

            supabase.table("Student").update(update_data).eq("phone_number",phone_number).execute()

            log_text = caption if caption else f"📎 Sent {message_type}: {clean_filename}"
            supabase.table("messages").insert({"phone_number": phone_number,
                "sender": "manager",
                "message_text": log_text}).execute()
            return {
                "status": "success",
                "message": f"Media {message_type} sent successfully.",
                "media_url": media_public_url,
                "meta_message_id": response_data.get("messages", [{}])[0].get("id")}
        else:
            return {
                "status": "meta_api_error",
                "http_code": response.status_code,
                "error_details": response_data
            }

    except Exception as e:
        return {"status": "backend_server_error", "detail": str(e)}
    
@app.get("/dashboard/students")
async def get_dashboard_students():
    try:
        response = supabase.table("Student").select("*").order("last_seen",desc = True,nullsfirst=False).execute()
        students = response.data
        current_time = datetime.datetime.now(datetime.timezone.utc)

        processed_student = []

        for student in students:
            s_data = dict(student)

            s_data["is_reminder_due"] = False
            
            ai_replies = s_data.get("ai_reply_count") or 0
            s_data["needs_escalation"] = True if ai_replies > 3 else False

            reminder_str = s_data.get("reminder_at")
            if reminder_str:
                reminder_time = datetime.datetime.fromisoformat(reminder_str.replace("z","+00:00"))

                if current_time >= reminder_time:
                    s_data["is_reminder_due"] = True
            processed_student.append(s_data)

        return {"status": "success", "students":processed_student}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/dashboard/clear-unread/{phone_number}")
def clear_unread_status(phone_number:str):
    """
    Removes the unread notification dot from the student's card 
    the exact second the manager opens their chat window.
    """
    try:
        supabase.table("Student").update({"has_unread":False}).eq("phone_number",phone_number).execute()
    except Exception as e:
        print(f"Database error clearing unread state:{e}")

class TakeoverRequest(BaseModel):
    phone_number:str

class SendMessageRequest(BaseModel):
    phone_number : str
    message_type : Literal["text", "image", "video", "document", "template"]
    message_text : Optional[str] = None
    media_url : Optional[HttpUrl] = None
    filename : Optional[str] = None
    template_var1:Optional[str] = None , 
    template_var2: Optional[str] = None


class ReminderRequest(BaseModel):
    phone_number:str
    remind_in_minutes:int

@app.post("/dashboard/set-reminder")
async def set_reminder(payload: ReminderRequest):
    try:
        phone_number = payload.phone_number
        remind_in_minutes = payload.remind_in_minutes

        current_time =  datetime.datetime.now(datetime.timezone.utc)
        future_reminder_time =current_time + datetime.timedelta(minutes=remind_in_minutes)

        supabase.table("Student").update({"reminder_at":future_reminder_time.isoformat()}).eq("phone_number",phone_number).execute()

        return {"status": "success", "message": f"Reminder locked for {remind_in_minutes} Minutes."}

    except Exception as e:
        print(f"❌ Reminder configuration error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/dashboard/takeover")
async def dashboard_takeover(data :TakeoverRequest):
    try:
        update_data = {"is_human_handling":True,"ai_reply_count":0}
        supabase.table("Student").update(update_data).eq("phone_number",data.phone_number).execute()
        print(f"Dashboard Switch Flipped! Bot paused for {data.phone_number}")
        return {"status": "success", "message": "Bot paused. Human control active."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    
def send_meta_whatsapp_request(url: str, headers: dict,basepayload:dict ,payload: dict):
    """Handles the slow outward network call to Meta and local Supabase database updates 
    asynchronous to the main thread so the user dashboard never lags."""

    try:
        response = requests.post(url,headers=headers,json=basepayload)
        response_data = response.json()

        if response.status_code == 200:
            current_time_string = datetime.datetime.now(datetime.timezone.utc).isoformat()
            update_data = {"last_seen": current_time_string,"reminder_at": None,"ai_reply_count":0}
            supabase.table("Student").update(update_data).eq("phone_number",payload["phone_number"]).execute()
            log_text = f"📢 Template Sent: {payload['message_text']}" if payload['message_type'] == "template" else payload['message_text']
            if not log_text and payload['message_type'] != "text":
                log_text = f"sent a {payload['message_type']}"

            supabase.table("messages").insert({
                "phone_number": payload["phone_number"],
                "sender": "manager",
                "message_text": log_text
                }).execute()
            print(f"✅ Meta Background Sync Success for +{payload['phone_number']}")

        else:
            print(f"❌ Meta API Error for +{payload['phone_number']}: {response_data}")

    except Exception as e:
        print(f"❌ Meta Background Sync Exception for +{payload['phone_number']}: {str(e)}")





@app.post("/dashboard/send-message")
async def dashboard_send_message(payload: SendMessageRequest,background_tasks: BackgroundTasks):
    try:
        print("--- DEBUG MESSAGE RECEIPT ---")
        print(f"RECEIVED TYPE: '{payload.message_type}' | RECEIVED TEXT: '{payload.message_text}'")
        print(f"--- TOKEN DEBUG --- Length: {len(meta_token)} | First 10 chars: '{meta_token[:10]}...'")
        url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization":f"Bearer {meta_token}",
            "Content-Type":"application/json"
        }

        base_payload = {
           "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": payload.phone_number,
            "type": payload.message_type 
        }
        print(f"--- BACKEND RECEIVED VARS --- Var1: {payload.template_var1} | Var2: {payload.template_var2}")

        if payload.media_url and payload.message_type == "document":
            if not payload.filename:
                payload.filename = os.path.basename(str(payload.media_url))

                if not payload.filename or "." not in payload.filename:
                    payload.filename = "Document.pdf"
        # 🟢 ADDED TEMPLATE CHECKER CONDITION:
        elif payload.message_type == "template":
            if not payload.message_text:
                raise HTTPException(status_code=400, details="Template type requires template registry name in 'message_text'")


            if payload.template_var1 or payload.template_var1.strip():
                student_name = payload.template_var1.strip()
        
            else:
                student_data = supabase.table("Student").select("name").eq("phone_number",payload.phone_number).execute()
                student_name = student_data.data[0].get("name","Learner") if student_data.data else "Learner"

            if payload.template_var2 or payload.template_var2.strip():
                student_course = payload.template_var2.strip()

            else:
                student_data = supabase.table("Student").select("goal").eq("phone_number",payload.phone_number).execute()
                student_course = student_data.data[0].get("goal","our certification programs") if student_data.data else "our certification programs"


            base_payload["template"] = {
                "name": payload.message_text, # Frontend sends the registry template name here
                "language": { "code": "en" }
            }
            # Inject variables dynamically into body parameters
            base_payload["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        { "type": "text", "text": student_name },     # {{1}}
                        { "type": "text", "text": student_course }   # {{2}}
                    ]
                }
            ]

        elif payload.message_type == "text":
            if not payload.message_text:
                raise HTTPException(status_code=400,details= "Text type requires 'message_text'")
            base_payload["text"] = {"body":payload.message_text}

        elif payload.message_type == "image":
            if not payload.media_url:
                raise HTTPException(status_code =400,details= "Image type requires 'media_url'")
            base_payload["image"] = {"link":str(payload.media_url)}

        elif payload.message_type == "video":
            if not payload.media_url:
                raise HTTPException(status_code = 400,details = "Video type requires 'media_url'" )
            base_payload["video"] = {"link":str(payload.media_url)}

        elif payload.message_type == "document":
            if not payload.media_url:
                raise HTTPException(status_code = 400,details = "Document type requires 'media_url'" )
            base_payload["document"] = {"link":str(payload.media_url),"filename":payload.filename}
            if payload.message_text:
                base_payload["document"]["caption"] = payload.message_text
        else:
            raise HTTPException(status_code=400, details="Invalid type. Use template,text, image, video, or document.")

        payload_data_summary = {
            "phone_number" :payload.phone_number,
            "message_type":payload.message_type,
            "message_text":payload.message_text,
        }

        background_tasks.add_task(send_meta_whatsapp_request,url,headers,base_payload,payload_data_summary)
        
        return {"status": "success", "message": "Message sent successfully."}

    except HTTPException as he:
        raise he
         
    except Exception as e:
        return {"status": "backend_server_error", "detail": str(e)}    

@app.get("/dashboard/messages/{phone_number}")
async def get_chat_history(phone_number: str):
    try:
        # Fetch all messages for this specific phone number, ordered oldest to newest
        # Clean the incoming number (remove "+" sign if the frontend passed it)
        clean_phone = phone_number.replace("+", "").strip()
        print(f"Fetching history logs for cleaned number: {clean_phone}")
        response = supabase.table("messages").select("sender","message_text","created_at","buttons").eq("phone_number", phone_number).order("created_at", desc=False).execute()        
        return {"status": "success", "messages": response.data}
    except Exception as e:
        return {"status": "error", "detail": str(e)}        



    
def type_detector(msg: str):
    msg = msg.lower().strip()
    words = msg.split()

    LOW_WORDS = ["ok", "okay", "hmm", "k", "fine"]
    QUESTION_WORDS = ["what", "how","fee", "fees","price", "cost","timing", "time","duration","structure"]


    is_low = any(word in words for word in LOW_WORDS)
    is_question = any(word in msg for word in QUESTION_WORDS)

    if is_question:
        return "Question"
    elif is_low:
        return "Low"
    else:
        return "Flow"

def question_handler(msg:str,phone_number:str):
    msg = msg.lower().strip()
    if any(word in msg for word in ["fee","price","cost"]):
        return (
            "Fees depend on the course 👍\n"
            "It usually ranges between ₹50k–₹1L\n\n"
            "You'll get complete brewakdown in demo")

    if any(word in msg for word in ["timing","schedule"]):
        return (
            "We have flexible timings 👍\n"
            "Morning & evening batches available.\n\n"
        )

    if any(word in msg for word in ["duration","how long"]):
        return (
            "Course duration depends on your level 👍\n"
            "Usually 6 months to 1 year.\n\n")
    response = generate_answer(msg)
    if response:
        student_res = supabase.table("Student").select("ai_reply_count").eq("phone_number",phone_number).execute()
        cuurent_count = 0
        if student_res.data:
            current_count = student_res.data[0].get("ai_reply_count") or 0

        new_count = current_count + 1

        supabase.table("Student").update({"ai_reply_count":new_count}).eq("phone_number",phone_number).execute()
        return response


      

def whatsapp_message(user_msg:str,user_number:str):
    """ whatsapp_message will handle the flow of user query 
    args : user_msg will actual message of user which message on whatsapp
           user_number will number of user who message this will used to send back the message to user
    """
    #normalizing the message
    msg = user_msg.strip().lower()

    #if user didn't reply like empty string ""
    if not user_msg:
        return "give your message"
    
    #we are dividing the user message in three type low high question because we can manage it easily. for low there is differnent answer  
    msg_type = type_detector(msg)
    
    
    if user_number not in user:

        user[user_number] = {
                "step": "ask_name",
                "name": "",
                "goal": "",
                "interest":"",
                "intent":"",
                "demo_date":"",
                "last_seen": datetime.datetime.now(),
                "followed_1h": False,
                "followed_24h": False
            }
        # HIGH INTENT
        if any(word in msg for word in ["demo", "join", "enroll", "admission", "start"]):    
            return send_text_message(
                "Great 🔥 Let's book a demo.\nCan I know your name?",
                user_number)

        # QUESTION
        if msg_type == "Question":
            answer = question_handler(msg,user_number)
            user[user_number]["step"] = "ask_goal"
            send_text_message(
                f"{answer}\n\nBy The Way, Which course are you preparing for ?",
                user_number)
            return send_button_message(body_text = "If you want to look others course just name it",buttons=[{"id":"python","title":"Python"},{"id":"web_development","title":"Web Development"},{"id":"data_science","title":"Data Science"}],to_number =user_number)

        return send_text_message(
            "hey 👋! Welcome to our coding  institute\nCan I know your name?",
            user_number)

    user[user_number]["last_seen"] = datetime.datetime.now()

    user[user_number]["followed_1h"] = False
    user[user_number]["followed_24h"] = False 
    #if user already in the history then take out the previous step when user message last time
    current_step = user[user_number]["step"]   
    #this will start the user flow  when user send starting message like hi then 
    if any(word in msg for word in ["hi","hello","hey"]) and current_step == "ask_name":
        #it easy to store and get the data so we use here dict
        user[user_number].update({
            "step": "ask_name",
            "name": "",
            "goal": "",
            "interest":"",
            "intent":"",
            "demo_date":"",
        })
        #we are returning the message to the fuction which will send to whatsapp by taking the number 
        return send_text_message("hey 👋! Welcome to our coding institute. can i know your name?",user_number)
    

    if current_step == "completed":
        if any(word in msg for word in ["ok", "okay", "thanks", "thank you"]):
            return send_text_message(
                "You're welcome 😊\nOur team will contact you soon.\nIf you need anything else, just message me 👍",
                user_number
            )
        
        if msg_type == "Question":
            answer = question_handler(msg,user_number)
            return send_text_message(answer+"\n\nBy the way,our team will explain everything in your demo ", user_number)
        if any(word in msg for word in ["hii","hi","hello","hey"]):
            return send_text_message("Hey! i am here tell me what you want ",user_number)
        return send_text_message(
            "👍 Noted!\nOur team will connect with you shortly.",
            user_number)
    # HANDLE DATE INPUT (SMART WAY)
    if (("today" in msg ) or ("tomorrow" in msg)) and not any(x in msg for x in ["not", "busy", "can't"]) or msg in ["today","tomorrow"] : 
        # CASE 1: user already in confirm step → FINAL BOOKING
        if current_step == "confirm_date" :
            supabase.table("Student").update({"demo_date": msg}).eq("phone_number",user_number).execute()
            daily_stats["Demo"] += 1
            user[user_number]["demo_date"] = msg
            user[user_number]["step"] ="completed"
            name = user[user_number]["name"]
            goal = user[user_number]["goal"]
            interest = user[user_number]["interest"]
            if user_number in leads_db:
                leads_db[user_number]["status"] = "demo_booked"

            return send_text_message(
                f"Great 👍 Your demo is confirmed for {msg}.Our team will contact you shortly.",
                user_number
            )

        # CASE 2: user NOT in confirm step → ASK CONFIRMATION
        else:
            user[user_number]["demo_date"] = msg
            user[user_number]["step"] = "confirm_date"

            return send_text_message(
                f"Just to confirm 👍\nDo you want the demo {msg}?",
                user_number)

    if current_step == "confirm_date":
        # ❌ USER REJECTS
        if any(word in msg for word in ["no", "not now", "later"]):
            return send_text_message(
                "No problem 👍 Let me know whenever you're ready.",
                user_number
            )
        # ⚠️ INVALID INPUT
        else:
            
            send_text_message(
                "Just to confirm 👍\nDo you want the demo today or tomorrow?",
                user_number)
            return send_button_message(body_text = "let me know if you want to book on other day",buttons = [{"id":"today","title":"Today"},{"id":"tomorrow","title":"Tomorrow"}],to_number = user_number)

    #if user come and ask question or not reply acording to the flow
    if msg_type == "Question" and current_step != "completed":
        answer = question_handler(msg,user_number)
        #this will take in to the flow
        if current_step == "ask_name":
            follow = "\n\nby the way what is your name?"
        elif current_step == "ask_goal":
            follow = "\n\nfor what purpose  are you preparing for?"
        else:
            send_text_message(answer,user_number)
            return send_button_message(body_text = "would you like to book a demo class?",buttons = [{"id":"demo_book","title":"Free Demo Class"}],to_number = user_number)

        return send_text_message(answer+follow,user_number)
    #if user come back answering like ok or fine then we smothly end it
    if msg_type == "Low":
        return send_button_message(body_text = "👍 Could you tell me what you're looking for?",buttons = [{"id":"demo","title":"Free Demo Class"},{"id":"fees_details","title":"Fees Details"},{"id":"full_info","title":"Full Course Info"}],to_number = user_number)
        
    #if user reply name 
    if current_step == "ask_name":
        user[user_number]["name"] = user_msg.strip()
        supabase.table("Student").update({"name": user[user_number]["name"]}).eq("phone_number",user_number).execute()
        #this will change the step and by this flow will maintain
        user[user_number]["step"] = "ask_goal"
        send_text_message(f"Nice To Meet You, {user[user_number]['name']}!",user_number)
        return send_button_message(body_text= "Which Course are you looking?",buttons=[{"id":"python","title":"Python"},{"id":"web_development","title":"Web Development"},{"id":"data_science","title":"Data Science"}],to_number = user_number)
    
    if current_step == "ask_goal":
        user[user_number]["goal"] = user_msg.strip()
        supabase.table("Student").update({"goal": user[user_number]["goal"]}).eq("phone_number",user_number).execute()
        user[user_number]["step"] = "ask_interest"
        send_text_message(f"Got it! what excatly are you looking for ?",user_number)
        return send_button_message(body_text = "If Anything else just tell me ",buttons = [{"id":"demo","title":"Free Demo Class"},{"id":"fees_details","title":"Fees Details"},{"id":"full_info","title":"Full Course Info"}],to_number = user_number)



    if current_step == "ask_interest":
        name = user[user_number]["name"] 
        user[user_number]["interest"] = user_msg.strip()
        interest = user[user_number]["interest"]
        supabase.table("Student").update({"interest": interest}).eq("phone_number",user_number).execute()
        daily_stats["total"] += 1
        #priority to highlight the lead to take action fastly 
        if any(i in interest for i in ["demo","trial","free class","book","Free Demo Class"])or msg == "demo_book":
            priority = "High Value"
            reason = "User directly asked for demo"
        else:
            #first we go for rule based classifier
            raw_info = coaching_classifier(interest)
            if not raw_info:
                #if that failed then we go for llm based
                raw_llm_info = llm_response(interest)
                if raw_llm_info:
                        student_res = supabase.table("Student").select("ai_reply_count").eq("phone_number",user_number).execute()
                        cuurent_count = 0
                        if student_res.data:
                            current_count = student_res.data[0].get("ai_reply_count") or 0
                
                        new_count = current_count + 1
                
                        supabase.table("Student").update({"ai_reply_count":new_count}).eq("phone_number",user_number).execute()
                #this will normalize the data from llm because we cant handle 100 % output format from it                      
                priority,reason = parser_classifier(raw_llm_info)
            elif raw_info:

                priority,reason = parser_classifier(raw_info)
        #saving the intent and all data in google sheet 
        user[user_number]["intent"] = priority
        supabase.table("Student").update({"priority":priority}).eq("phone_number",user_number).execute()
        supabase.table("Student").update({"reason":reason}).eq("phone_number",user_number).execute()
        name = user[user_number]["name"]
        goal = user[user_number]["goal"]
        save_to_google_sheets(name,user_number,f"{goal}|{interest}",priority,reason)
        lead = {
            "name":name,
            "phone":user_number,
            "goal": goal,
            "interest":interest,
            "priority":priority,
            "timestamp":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status":"new"}
        leads_db[user_number] = lead
        today =  datetime.datetime.now()
        if daily_stats["date"].date() != today.date():
            daily_stats.update({    
                "date":datetime.datetime.now(),
                "total":0,
                "High":0,
                "Medium":0,
                "Low":0,
                "Demo":0 })
        #this is convert the user and tell for attend the demo class    
        if priority == "High Value":
            daily_stats["High"] += 1
            owner_number = os.getenv("owner_number")
            alert_text = f"""HOT LEAD ALERT(CALL NOW)
            Name: {name}
            Number:{user_number}
            Goal:{goal}
            interest:{interest}"""    

            send_text_message(alert_text,owner_number)
            user[user_number]["step"] = "confirm_date"
            return send_button_message(body_text = "Perfect 🔥\nWe have a demo session available for ",buttons = [{"id":"today","title":"Today"},{"id":"tomorrow","title":"Tomorrow"}],to_number = user_number)

        elif priority == "Medium Value" or msg == "full_info":
            daily_stats["Medium"] += 1
            #if user intent is medium then we will handle that by telling the demo
            user[user_number]["step"] = "demo_push"
        
            send_text_message(f"Here’s our detailed course syllabus & roadmap 👇\nThis will help you understand everything clearly before joining.\n\nhttps://drive.google.com/file/d/1w_DX2veGfdo_-0WochyGHfytlcKcD6f2/view?usp=drive_link",user_number)

            return send_button_message(body_text = "Most student attend a demo before joining 👍\n Should I book one for you?",buttons = [{"id":"demo_book","title":"Free Demo Class"}],to_number = user_number)
        else:
            daily_stats["Low"] += 1
            return send_text_message("""Got it 👍
Let me know if you'd like to demo class or need any details""",user_number)
    
    if current_step == "demo_push":
        if any(word in msg for word in ["ok","yeah","okay","sure","yes","demo","book","trial","class"]) or msg == "demo_book":
            user[user_number]["step"] = "confirm_date"
            name = user[user_number]["name"]
            goal = user[user_number]["goal"]
            interest = user[user_number]["interest"]
            owner_number = os.getenv("owner_number")
            alert_text = f"""HOT LEAD ALERT(CALL NOW)
            Name: {name}
            Number:{user_number}
            Goal:{goal}
            interest:{interest}"""    

            send_text_message(alert_text,owner_number)
            return send_button_message(body_text = "Perfect 🔥\nWe have a demo session available for ",buttons = [{"id":"today","title":"Today"},{"id":"tomorrow","title":"Tomorrow"}],to_number=user_number)
        else:
            return send_text_message("No Worries!\n\n Feel free ask anything antime!",user_number)
    
    
    response = generate_answer(msg)
    if response:
            student_res = supabase.table("Student").select("ai_reply_count").eq("phone_number",user_number).execute()
            cuurent_count = 0
            if student_res.data:
                current_count = student_res.data[0].get("ai_reply_count") or 0
    
            new_count = current_count + 1
    
            supabase.table("Student").update({"ai_reply_count":new_count}).eq("phone_number",user_number).execute()
            return send_text_message(response,user_number)

def send_report_daily():
    owner_number = os.getenv("owner_number")
    report = report = f"""
    📊 DAILY REPORT

    Total Leads: {daily_stats['total']}
    🔥 High Value: {daily_stats['High']}
    🔥Medium Value:{daily_stats["Medium"]}
    ⚫ Low Value: {daily_stats['Low']}
    📅 Demo Booked: {daily_stats['Demo']}"""
    send_text_message(report,owner_number)

def report_scheduler():
    while True:
        now =  datetime.datetime.now()
        if now.hour == 0 and now.minute == 44:
            print(now)
            send_report_daily()
            time.sleep(60)
        time.sleep(10)

threading.Thread(target = report_scheduler,daemon = True).start()

@app.get("/leads")
def get_leads(priority :str =None,status :str =None):
    data = list(leads_db.values())
    if priority:
        data = [l for l in data if l["priority"].lower() == priority.lower()]
    if status:
        data = [l for l in data if l["status"].lower() == status.lower()]
    return {"leads":data}