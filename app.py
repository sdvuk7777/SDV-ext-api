from flask import Flask, request, jsonify, send_file
import requests
import os
import time
import logging
import itertools
import gunicorn

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Constants
ROOT_DIR = os.environ.get('TEMP_DIRECTORY', '/tmp')
PORT = int(os.environ.get('PORT', 8080))

# Create directory if it doesn't exist
os.makedirs(ROOT_DIR, exist_ok=True)

# KGS Functions
def kgs_login_with_credentials(user_id, password):
    """Login with ID and password and return the token."""
    try:
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
        
        logger.info(f"Attempting KGS login for user: {user_id}")
        response = requests.post(login_url, headers=headers, data=data, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"KGS login failed with status code: {response.status_code}")
            return None
        
        try:
            response_data = response.json()
            token = response_data.get("token")
            if token:
                logger.info("KGS login successful")
                return token
            else:
                logger.error("No token found in KGS response")
                return None
        except ValueError as e:
            logger.error(f"Failed to parse KGS login response: {e}")
            return None
    except Exception as e:
        logger.error(f"Exception during KGS login: {e}")
        return None

def kgs_get_batches(token):
    """Fetch batches using the token."""
    try:
        headers = {
            "Host": "khanglobalstudies.com",
            "authorization": f"Bearer {token}",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.9.1",
        }
        
        logger.info("Fetching KGS courses")
        course_response = requests.get(
            "https://khanglobalstudies.com/api/user/v2/courses",
            headers=headers,
            timeout=30
        )
        
        if course_response.status_code != 200:
            logger.error(f"Failed to fetch KGS courses: {course_response.status_code}")
            return None
        
        return course_response.json()
    except Exception as e:
        logger.error(f"Exception while fetching KGS batches: {e}")
        return None

def kgs_extract_content(token, batch_id):
    """Extract content from a batch and return the file path."""
    try:
        headers = {
            "Host": "khanglobalstudies.com",
            "authorization": f"Bearer {token}",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.9.1",
        }
        
        lessons_url = f"https://khanglobalstudies.com/api/user/courses/{batch_id}/v2-lessons"
        logger.info(f"Fetching lessons for batch: {batch_id}")
        lessons_response = requests.get(lessons_url, headers=headers)
        
        if lessons_response.status_code != 200:
            logger.error(f"Failed to fetch lessons: {lessons_response.status_code}")
            return None
        
        lessons = lessons_response.json()
        full_content = ""
        lesson_count = len(lessons)
        logger.info(f"Found {lesson_count} lessons to process")
        
        for i, lesson in enumerate(lessons):
            try:
                lesson_id = lesson['id']
                logger.info(f"Processing lesson {i+1}/{lesson_count}: {lesson_id}")
                lesson_url = f"https://khanglobalstudies.com/api/lessons/{lesson_id}"
                lesson_response = requests.get(lesson_url, headers=headers)
                
                if lesson_response.status_code != 200:
                    logger.warning(f"Failed to fetch lesson {lesson_id}: {lesson_response.status_code}")
                    continue
                    
                lesson_data = lesson_response.json()
                videos = lesson_data.get("videos", [])
                
                for video in videos:
                    title = video.get("name", "Untitled").replace(":", " ")
                    video_url = video.get("video_url", "")
                    if video_url:
                        full_content += f"{title}: {video_url}\n"
            except Exception as e:
                logger.error(f"Error processing lesson {lesson.get('id', 'unknown')}: {e}")
                continue
        
        if full_content:
            filename = f"KGS_{batch_id}.txt"
            file_path = os.path.join(ROOT_DIR, filename)
            
            logger.info(f"Writing content to file: {file_path}")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            
            return file_path
        else:
            logger.warning("No content extracted")
            return None
    except Exception as e:
        logger.error(f"Exception during KGS content extraction: {e}")
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
        logger.info("Fetching PW batches")
        for page in itertools.count(1):
            if page > 10:  # Safety limit to prevent infinite loops
                logger.warning("Reached page limit (10) when fetching PW batches")
                break
                
            logger.info(f"Fetching PW batches page {page}")
            response = requests.get(
                f'https://api.penpencil.xyz/v3/batches/my-batches?page={page}&mode=1',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 401:
                logger.error("Invalid or expired PW token")
                return "TOKEN_ERROR"

            if response.status_code != 200:
                logger.error(f"Failed to fetch PW batches. Status code: {response.status_code}")
                break

            data = response.json().get("data", [])
            if not data:
                logger.info(f"No more batches on page {page}")
                break

            logger.info(f"Found {len(data)} batches on page {page}")
            for batch in data:
                batch_id = batch["_id"]
                name = batch["name"]
                price = batch.get("feeId", {}).get("total", "Free")
                result.append({
                    "batch_id": batch_id,
                    "batch_name": name,
                    "price": price
                })
                
        logger.info(f"Total PW batches found: {len(result)}")
    except ValueError as ve:
        logger.error(f"PW Token Error: {ve}")
        return "TOKEN_ERROR"
    except Exception as e:
        logger.error(f"Unexpected Error in PW batches: {e}")
        return None

    return result

def pw_get_subjects(batch_id, auth_code):
    """Fetch all subjects for a given batch."""
    try:
        headers = {
            'authorization': f"Bearer {auth_code}",
            'client-id': '5eb393ee95fab7468a79d189',
            'user-agent': 'Android',
        }

        logger.info(f"Fetching subjects for batch: {batch_id}")
        response = requests.get(
            f'https://api.penpencil.xyz/v3/batches/{batch_id}/details', 
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json().get("data", {})
            subjects = data.get("subjects", [])
            logger.info(f"Found {len(subjects)} subjects")
            return subjects
        else:
            logger.error(f"Failed to fetch subjects. Status code: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Exception while fetching PW subjects: {e}")
        return []

def pw_extract_content(batch_id, auth_code, content_type):
    """Extract content for a given batch and content type."""
    try:
        subjects = pw_get_subjects(batch_id, auth_code)
        if not subjects:
            logger.warning(f"No subjects found for batch {batch_id}")
            return None

        full_content = ""
        start_time = time.time()
        logger.info(f"Starting content extraction for {len(subjects)} subjects, type: {content_type}")

        for i, subject in enumerate(subjects):
            subject_id = subject["_id"]
            subject_name = subject["subject"]
            logger.info(f"Processing subject {i+1}/{len(subjects)}: {subject_name}")
            full_content += f"\n\n=== Subject: {subject_name} ===\n\n"

            page = 1
            items_found = 0
            while True:
                if page > 30:  # Safety limit to prevent infinite loops
                    logger.warning(f"Reached page limit (30) for subject: {subject_name}")
                    break
                    
                logger.info(f"Fetching {content_type} data for {subject_name}, page {page}")
                subject_data = pw_get_batch_contents(batch_id, subject_id, page, auth_code, content_type)
                
                if not subject_data:
                    logger.info(f"No more data for subject {subject_name} on page {page}")
                    break

                for item in subject_data:
                    items_found += 1
                    if content_type == "exercises-notes-videos":
                        full_content += f"{item.get('topic', 'Untitled')}: {item.get('url', '').strip()}\n"
                    elif content_type == "notes":
                        if item.get('homeworkIds'):
                            homework = item['homeworkIds'][0]
                            if homework.get('attachmentIds'):
                                attachment = homework['attachmentIds'][0]
                                full_content += f"{homework.get('topic', 'Untitled')}: {attachment.get('baseUrl', '') + attachment.get('key', '')}\n"
                    elif content_type == "DppNotes":
                        if item.get('homeworkIds'):
                            for homework in item['homeworkIds']:
                                if homework.get('attachmentIds'):
                                    attachment = homework['attachmentIds'][0]
                                    full_content += f"{homework.get('topic', 'Untitled')}: {attachment.get('baseUrl', '') + attachment.get('key', '')}\n"
                    elif content_type == "DppSolution":
                        url = item.get('url', '').replace("d1d34p8vz63oiq", "d26g5bnklkwsh4").replace("mpd", "m3u8").strip()
                        full_content += f"{item.get('topic', 'Untitled')}: {url}\n"

                page += 1
                
            logger.info(f"Found {items_found} items for subject {subject_name}")

        elapsed_time = time.time() - start_time
        logger.info(f"Content extraction complete. Time taken: {elapsed_time:.2f} seconds")

        if full_content:
            filename = f"PW_{batch_id}_{content_type}.txt"
            file_path = os.path.join(ROOT_DIR, filename)
            
            logger.info(f"Writing content to file: {file_path}")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(full_content)

            return file_path
        else:
            logger.warning("No content extracted")
            return None
    except Exception as e:
        logger.error(f"Exception during PW content extraction: {e}")
        return None

def pw_get_batch_contents(batch_id, subject_id, page, auth_code, content_type):
    """Fetch content for a given subject."""
    try:
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
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            logger.info(f"Found {len(data)} items on page {page}")
            return data
        else:
            logger.error(f"Failed to fetch batch contents. Status code: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Exception while fetching batch contents: {e}")
        return []

# Create an error handler
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle exceptions globally to prevent app from crashing."""
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "Internal server error", "message": str(e)}), 500

# Health check endpoint for Koyeb
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Server is running"})

# KGS Endpoints
@app.route('/kgs/get_batches', methods=['GET'])
def kgs_get_batches_endpoint():
    """Endpoint to get batch information for KGS."""
    try:
        credentials = request.args.get('credentials')
        if not credentials:
            return jsonify({"error": "Credentials are required"}), 400
            
        logger.info("Received request for KGS batches")
        
        if '*' in credentials:
            user_id, password = credentials.split('*', 1)
            token = kgs_login_with_credentials(user_id, password)
        else:
            token = credentials
        
        if not token:
            return jsonify({"error": "Login failed"}), 401
        
        batches = kgs_get_batches(token)
        
        if not batches:
            return jsonify({"error": "Failed to fetch batches or no batches found"}), 404
        
        batch_info = []
        for batch in batches:
            batch_info.append({
                "batch_id": batch['id'],
                "batch_name": batch['title']
            })
        
        logger.info(f"Retrieved {len(batch_info)} KGS batches")
        return jsonify({"batches": batch_info})
    except Exception as e:
        logger.error(f"Error in KGS get_batches endpoint: {e}")
        return jsonify({"error": "Failed to get batches", "message": str(e)}), 500

@app.route('/kgs/extract', methods=['GET'])
def kgs_extract_endpoint():
    """Endpoint to extract content for KGS."""
    try:
        credentials = request.args.get('credentials')
        batch_id = request.args.get('batch_id')
        
        if not credentials or not batch_id:
            return jsonify({"error": "Credentials and batch_id are required"}), 400
            
        logger.info(f"Received request to extract content for KGS batch: {batch_id}")
        
        if '*' in credentials:
            user_id, password = credentials.split('*', 1)
            token = kgs_login_with_credentials(user_id, password)
        else:
            token = credentials
        
        if not token:
            return jsonify({"error": "Login failed"}), 401
        
        file_path = kgs_extract_content(token, batch_id)
        
        if not file_path:
            return jsonify({"error": "No content found or extraction failed"}), 404
        
        logger.info(f"Sending file: {file_path}")
        return send_file(file_path, as_attachment=True, download_name=f"KGS_{batch_id}.txt")
    except Exception as e:
        logger.error(f"Error in KGS extract endpoint: {e}")
        return jsonify({"error": "Failed to extract content", "message": str(e)}), 500

# PW Endpoints
@app.route('/pw/get_batches', methods=['GET'])
def pw_get_batches_endpoint():
    """Endpoint to get batch information for PW."""
    try:
        auth_code = request.args.get('auth_code')
        
        if not auth_code:
            return jsonify({"error": "Authentication code is required"}), 400
            
        logger.info("Received request for PW batches")
        
        batches = pw_get_batches(auth_code)
        
        if batches == "TOKEN_ERROR":
            return jsonify({"error": "Invalid or expired token"}), 401
        
        if not batches:
            return jsonify({"error": "No batches found or failed to fetch"}), 404
        
        logger.info(f"Retrieved {len(batches)} PW batches")
        return jsonify({"batches": batches})
    except Exception as e:
        logger.error(f"Error in PW get_batches endpoint: {e}")
        return jsonify({"error": "Failed to get batches", "message": str(e)}), 500

@app.route('/pw/extract', methods=['GET'])
def pw_extract_endpoint():
    """Endpoint to extract content for PW."""
    try:
        auth_code = request.args.get('auth_code')
        batch_id = request.args.get('batch_id')
        content_type = request.args.get('content_type')
        
        if not auth_code or not batch_id or not content_type:
            return jsonify({"error": "auth_code, batch_id, and content_type are required"}), 400
            
        logger.info(f"Received request to extract content for PW batch: {batch_id}, type: {content_type}")
        
        file_path = pw_extract_content(batch_id, auth_code, content_type)
        
        if not file_path:
            return jsonify({"error": "No content found or extraction failed"}), 404
        
        logger.info(f"Sending file: {file_path}")
        return send_file(file_path, as_attachment=True, download_name=f"PW_{batch_id}_{content_type}.txt")
    except Exception as e:
        logger.error(f"Error in PW extract endpoint: {e}")
        return jsonify({"error": "Failed to extract content", "message": str(e)}), 500

# For local development
if __name__ == '__main__':
    # Use PORT environment variable if provided by Koyeb
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port)