from flask import Flask, request, jsonify, send_file
import requests
import os
import time
import logging
import itertools

app = Flask(__name__)

# Constants
ROOT_DIR = os.getcwd()

# KGS Functions
def kgs_login_with_credentials(user_id, password):
    """Login with ID and password and return the token."""
    headers = {
        "Host": "khanglobalstudies.com",
        "content-type": "application/x-www-form-urlencoded",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/3.9.1",
    }
    
    login_url = "https://khanglobalstudies.com/api/login-with-password"
    data = {
        "phone": user_id,
        "password": password,
    }
    
    response = requests.post(login_url, headers=headers, data=data, timeout=30)
    
    if response.status_code != 200:
        return None
    
    try:
        response_data = response.json()
        return response_data.get("token")
    except ValueError:
        return None

def kgs_get_batches(token):
    """Fetch batches using the token."""
    headers = {
        "Host": "khanglobalstudies.com",
        "authorization": f"Bearer {token}",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/3.9.1",
    }
    
    course_response = requests.get(
        "https://khanglobalstudies.com/api/user/v2/courses",
        headers=headers,
        timeout=30
    )
    
    if course_response.status_code != 200:
        return None
    
    return course_response.json()

def kgs_extract_content(token, batch_id):
    """Extract content from a batch and return the file path."""
    headers = {
        "Host": "khanglobalstudies.com",
        "authorization": f"Bearer {token}",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/3.9.1",
    }
    
    lessons_url = f"https://khanglobalstudies.com/api/user/courses/{batch_id}/v2-lessons"
    lessons_response = requests.get(lessons_url, headers=headers)
    
    if lessons_response.status_code != 200:
        return None
    
    lessons = lessons_response.json()
    full_content = ""
    
    for lesson in lessons:
        try:
            lesson_url = f"https://khanglobalstudies.com/api/lessons/{lesson['id']}"
            lesson_response = requests.get(lesson_url, headers=headers)
            lesson_data = lesson_response.json()

            videos = lesson_data.get("videos", [])
            for video in videos:
                title = video.get("name", "Untitled").replace(":", " ")
                video_url = video.get("video_url", "")
                if video_url:
                    full_content += f"{title}: {video_url}\n"
        except Exception as e:
            logging.error(f"Error processing lesson {lesson['id']}: {e}")
            continue
    
    if full_content:
        filename = f"KGS_{batch_id}.txt"
        file_path = os.path.join(ROOT_DIR, filename)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        
        return file_path
    else:
        return None

# PW Functions
def pw_get_batches(auth_code):
    """Fetch batches using the provided token."""
    headers = {
        'authorization': f"Bearer {auth_code}",
        'client-id': '5eb393ee95fab7468a79d189',
        'user-agent': 'Android',
    }

    result = []
    try:
        for page in itertools.count(1):
            response = requests.get(
                f'https://api.penpencil.xyz/v3/batches/my-batches?page={page}&mode=1',
                headers=headers,
            )
            if response.status_code == 401:
                raise ValueError("Invalid or expired token")

            if response.status_code != 200:
                logging.error(f"Failed to fetch batches. Status code: {response.status_code}")
                break

            data = response.json().get("data", [])
            if not data:
                break

            for batch in data:
                batch_id = batch["_id"]
                name = batch["name"]
                price = batch.get("feeId", {}).get("total", "Free")
                result.append({
                    "batch_id": batch_id,
                    "batch_name": name,
                    "price": price
                })
    except ValueError as ve:
        logging.error(f"Token Error: {ve}")
        return "TOKEN_ERROR"
    except Exception as e:
        logging.error(f"Unexpected Error: {e}")
        return None

    return result

def pw_get_subjects(batch_id, auth_code):
    """Fetch all subjects for a given batch."""
    headers = {
        'authorization': f"Bearer {auth_code}",
        'client-id': '5eb393ee95fab7468a79d189',
        'user-agent': 'Android',
    }

    response = requests.get(f'https://api.penpencil.xyz/v3/batches/{batch_id}/details', headers=headers)
    if response.status_code == 200:
        data = response.json().get("data", {})
        return data.get("subjects", [])
    else:
        logging.error(f"Failed to fetch subjects. Status code: {response.status_code}")
        return []

def pw_extract_content(batch_id, auth_code, content_type):
    """Extract content for a given batch and content type."""
    subjects = pw_get_subjects(batch_id, auth_code)
    if not subjects:
        return None

    full_content = ""
    start_time = time.time()

    for subject in subjects:
        subject_id = subject["_id"]
        subject_name = subject["subject"]
        full_content += f"\n\n=== Subject: {subject_name} ===\n\n"

        page = 1
        while True:
            subject_data = pw_get_batch_contents(batch_id, subject_id, page, auth_code, content_type)
            if not subject_data:
                break

            for item in subject_data:
                if content_type == "exercises-notes-videos":
                    full_content += f"{item['topic']}: {item['url'].strip()}\n"
                elif content_type == "notes":
                    if item.get('homeworkIds'):
                        homework = item['homeworkIds'][0]
                        if homework.get('attachmentIds'):
                            attachment = homework['attachmentIds'][0]
                            full_content += f"{homework['topic']}: {attachment['baseUrl'] + attachment['key']}\n"
                elif content_type == "DppNotes":
                    if item.get('homeworkIds'):
                        for homework in item['homeworkIds']:
                            if homework.get('attachmentIds'):
                                attachment = homework['attachmentIds'][0]
                                full_content += f"{homework['topic']}: {attachment['baseUrl'] + attachment['key']}\n"
                elif content_type == "DppSolution":
                    url = item['url'].replace("d1d34p8vz63oiq", "d26g5bnklkwsh4").replace("mpd", "m3u8").strip()
                    full_content += f"{item['topic']}: {url}\n"

            page += 1

    if full_content:
        filename = f"PW_{batch_id}_{content_type}.txt"
        file_path = os.path.join(ROOT_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(full_content)

        return file_path
    else:
        return None

def pw_get_batch_contents(batch_id, subject_id, page, auth_code, content_type):
    """Fetch content for a given subject."""
    headers = {
        'authorization': f"Bearer {auth_code}",
        'client-id': '5eb393ee95fab7468a79d189',
        'user-agent': 'Android',
    }

    params = {'page': page, 'contentType': content_type}
    response = requests.get(
        f'https://api.penpencil.xyz/v2/batches/{batch_id}/subject/{subject_id}/contents',
        params=params,
        headers=headers,
    )
    if response.status_code == 200:
        return response.json().get("data", [])
    else:
        logging.error(f"Failed to fetch batch contents. Status code: {response.status_code}")
        return []

# KGS Endpoints
@app.route('/kgs/get_batches', methods=['GET'])
def kgs_get_batches_endpoint():
    """Endpoint to get batch information for KGS."""
    credentials = request.args.get('credentials')
    
    if '*' in credentials:
        user_id, password = credentials.split('*', 1)
        token = kgs_login_with_credentials(user_id, password)
    else:
        token = credentials
    
    if not token:
        return jsonify({"error": "Login failed"}), 401
    
    batches = kgs_get_batches(token)
    
    if not batches:
        return jsonify({"error": "Failed to fetch batches"}), 500
    
    batch_info = []
    for batch in batches:
        batch_info.append({
            "batch_id": batch['id'],
            "batch_name": batch['title']
        })
    
    return jsonify({"batches": batch_info})

@app.route('/kgs/extract', methods=['GET'])
def kgs_extract_endpoint():
    """Endpoint to extract content for KGS."""
    credentials = request.args.get('credentials')
    batch_id = request.args.get('batch_id')
    
    if '*' in credentials:
        user_id, password = credentials.split('*', 1)
        token = kgs_login_with_credentials(user_id, password)
    else:
        token = credentials
    
    if not token:
        return jsonify({"error": "Login failed"}), 401
    
    file_path = kgs_extract_content(token, batch_id)
    
    if not file_path:
        return jsonify({"error": "No content found"}), 404
    
    return send_file(file_path, as_attachment=True)

# PW Endpoints
@app.route('/pw/get_batches', methods=['GET'])
def pw_get_batches_endpoint():
    """Endpoint to get batch information for PW."""
    auth_code = request.args.get('auth_code')
    
    if not auth_code:
        return jsonify({"error": "Authentication code is required"}), 400
    
    batches = pw_get_batches(auth_code)
    
    if batches == "TOKEN_ERROR":
        return jsonify({"error": "Invalid or expired token"}), 401
    
    if not batches:
        return jsonify({"error": "No batches found or failed to fetch"}), 404
    
    return jsonify({"batches": batches})

@app.route('/pw/extract', methods=['GET'])
def pw_extract_endpoint():
    """Endpoint to extract content for PW."""
    auth_code = request.args.get('auth_code')
    batch_id = request.args.get('batch_id')
    content_type = request.args.get('content_type')
    
    if not auth_code or not batch_id or not content_type:
        return jsonify({"error": "auth_code, batch_id, and content_type are required"}), 400
    
    file_path = pw_extract_content(batch_id, auth_code, content_type)
    
    if not file_path:
        return jsonify({"error": "No content found"}), 404
    
    return send_file(file_path, as_attachment=True, download_name=f"PW_{batch_id}_{content_type}.txt")

if __name__ == '__main__':
    app.run(debug=True)
