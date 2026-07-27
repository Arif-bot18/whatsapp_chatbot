import requests
from config import META_TOKEN, PHONE_NUMBER_ID,VERSION,supabase



def send_text_message(user_msg:str,to_number:str) -> requests.Response:
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization":f"Bearer {META_TOKEN}",
        "Content-Type":"application/json"
    }


    data = {
        "messaging_product":"whatsapp",
        "recipient_type":"individual",
        "to":to_number,
        "type":"text",
        "text":{
             "body":user_msg
        },
    }

    try:

        response = requests.post(url,headers=headers,json=data)

        if response.status_code == 200:
            print(f"Message sent successfully to {to_number}")
            supabase.table("messages").insert({
                "phone_number": to_number,
                "sender": "bot",
                "message_text": user_msg
            }).execute()
            return response.json()
        else:
            print(f"Failed to send message. Status: {response.status_code}")
            print(f"Error Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"An error occurred while sending: {e}")
        return None

def send_button_message(body_text:str, buttons:list,to_number:str) -> requests.Response:
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization":f"Bearer {META_TOKEN}",
        "Content_Type":"application/json"
    }

    whatsapp_buttons = []

    for button in buttons:
        whatsapp_buttons.append({
            "type":"reply",
            "reply":{
                "id":button["id"],
                "title":button["title"]
            }
        })

    data = {
        "messaging_product":"whatsapp",
        "recipitent_type":"individual",
        "to":to_number,
        "type":"interactive",
        "interactive":{
            "type":"button",
            "body":{
                "text": body_text,
            },
            "footer":{
                "text":"select an option below"
            },
            "action":{
                "buttons":whatsapp_buttons
                }
            }
        }
    try:
        response = requests.post(url,headers=headers,json=data)

        if response.status_code == 200:
            print(f"Message sent successfully to {to_number}")
            btn_title = [str(b.get("title","")) for b in buttons if isinstance(b,dict)]

            btn_note = btn_title if btn_title else ""
            supabase.table("messages").insert({
                "phone_number": to_number,
                "sender": "bot",
                "message_text": body_text if body_text else "",
                "buttons" : btn_note
            }).execute()
            return response.json()
        else:
            print(f"Failed to send message. Status: {response.status_code}")
            print(f"Error Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"An error occurred while sending: {e}")
        return None