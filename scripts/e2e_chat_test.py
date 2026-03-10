import os
import sys
import django
import requests
import json
import urllib3

# Suppress insecure request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup Django environment
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'apps', 'web'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apps.web.CodePathfinder.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from projects.models import PathfinderProject

User = get_user_model()

def run_test():
    # 1. Get a test user (Superuser)
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        print("❌ No superuser found. Please create one.")
        return

    print(f"✅ Using user: {user.username}")

    # 2. Get a valid project
    project = PathfinderProject.objects.filter(user=user, is_enabled=True).first()
    if not project:
        # Try shared
        project = PathfinderProject.objects.filter(is_enabled=True).first()
    
    if not project:
        print("❌ No active project found.")
        return

    print(f"✅ Using project: {project.name} (ID: {project.id})")

    # 3. Create a valid Session
    session = SessionStore()
    # session[settings.SESSION_COOKIE_NAME] = user.id  # Not needed
    session['_auth_user_id'] = str(user.id)
    session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    session['_auth_user_hash'] = user.get_session_auth_hash()
    session.save()
    session_key = session.session_key
    print(f"✅ Created session: {session_key}")

    # 4. Prepare Client
    client = requests.Session()
    client.cookies.set(settings.SESSION_COOKIE_NAME, session_key)
    client.verify = False  # Localhost self-signed
    
    base_url = "https://localhost:8443"

    # 5. GET Chat Page (to get CSRF token)
    print("🔄 Fetching chat page for CSRF...")
    try:
        resp = client.get(f"{base_url}/chat/{project.id}/")
        if resp.status_code != 200:
            print(f"❌ Failed to load chat page: {resp.status_code}")
            return
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    # Extract CSRF token
    csrf_token = client.cookies.get('csrftoken')
    if not csrf_token:
        print("❌ Could not get CSRF token")
        return
    
    print(f"✅ CSRF Token obtained")

    # 6. Create Conversation
    print("🔄 Creating conversation...")
    msg = "What is the name and size of this repo?"
    headers = {
        "X-CSRFToken": csrf_token,
        "Referer": f"{base_url}/chat/{project.id}/"
    }
    payload = {
        "project_id": project.id,
        "message": msg
    }
    
    resp = client.post(f"{base_url}/chat/create/", json=payload, headers=headers)
    if resp.status_code != 200:
        print(f"❌ Creation failed: {resp.status_code} - {resp.text}")
        return

    data = resp.json()
    conv_id = data['conversation_id']
    msg_id = data['message_id']
    print(f"✅ Conversation created: {conv_id}")

    # 7. Stream Response
    print("🔄 Starting stream (Connecting to Nginx)...")
    stream_url = f"{base_url}/chat/api/stream/?project={project.id}&conversation={conv_id}&message_id={msg_id}"
    
    try:
        with client.get(stream_url, stream=True, timeout=120) as r:
            if r.status_code != 200:
                print(f"❌ Stream failed: {r.status_code}")
                return
            
            print("🌊 Stream connected! Listening for events...")
            full_text = ""
            for line in r.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith(": keep-alive"):
                        print("💓 Keep-alive received")
                    elif decoded.startswith("data: "):
                        try:
                            json_data = json.loads(decoded[6:])
                            # Accumulate text
                            if isinstance(json_data, str): # Simple text
                                full_text += json_data
                                print(f"📝 {json_data}", end="", flush=True)
                            elif isinstance(json_data, dict):
                                # Check for tool call or other structure
                                pass 
                        except:
                            pass
                    elif decoded.startswith("event: "):
                         print(f"\n🔔 Event: {decoded[7:]}")

            print("\n✅ Stream finished.")
            print("-" * 40)
            print("Response Analysis:")
            if "scs" in full_text.lower():
                print("✅ Context seems correct (found 'scs' or related terms? Check manually)")
            else:
                 print("⚠️ Response content check:")
                 print(full_text)

    except requests.exceptions.ChunkedEncodingError:
        print("\n❌ ChunkedEncodingError: Connection cut mid-stream!")
    except Exception as e:
        print(f"\n❌ Stream Error: {e}")

if __name__ == "__main__":
    run_test()
