from flask import Flask, request, jsonify, render_template, redirect, url_for
from supabase import create_client, Client
import bcrypt
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# ─── Supabase config ────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Page routes ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/homepage')
def homepage():
    return render_template('homepage.html')

@app.route('/notes')
def notes():
    return render_template('notes.html')

@app.route('/upload')
def upload_page():
    return render_template('uploadpage.html')

@app.route('/myacc')
def myacc():
    return render_template('myacc.html')


# ─── Auth API ────────────────────────────────────────────────────────────────
@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    full_name        = data.get('full_name', '').strip()
    username         = data.get('username', '').strip()
    email            = data.get('email', '').strip().lower()
    password         = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not all([full_name, username, email, password, confirm_password]):
        return jsonify({'error': 'All fields are required.'}), 400

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400

    # Check if email already exists
    existing = supabase.table('users').select('id').eq('email', email).execute()
    if existing.data:
        return jsonify({'error': 'Email is already registered.'}), 409

    # Check if username already exists
    existing_user = supabase.table('users').select('id').eq('username', username).execute()
    if existing_user.data:
        return jsonify({'error': 'Username is already taken.'}), 409

    # Hash password
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Insert into Supabase
    result = supabase.table('users').insert({
        'full_name': full_name,
        'username':  username,
        'email':     email,
        'password':  hashed,
        'created_at': datetime.utcnow().isoformat()
    }).execute()

    if result.data:
        return jsonify({'message': 'Registration successful!'}), 201
    else:
        return jsonify({'error': 'Registration failed. Please try again.'}), 500


@app.route('/login', methods=['POST'])
def login_user():
    data     = request.get_json()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required.'}), 400

    # Fetch user from Supabase
    result = supabase.table('users').select('*').eq('email', email).execute()

    if not result.data:
        return jsonify({'error': 'Invalid email or password.'}), 401

    user = result.data[0]

    # Verify password
    if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        return jsonify({'error': 'Invalid email or password.'}), 401

    return jsonify({
        'user_id':   user['id'],
        'full_name': user['full_name'],
        'username':  user['username'],
        'email':     user['email']
    }), 200


@app.route('/change-password', methods=['POST'])
def change_password():
    data         = request.get_json()
    user_id      = data.get('user_id')
    new_password = data.get('new_password', '')

    if not user_id or not new_password:
        return jsonify({'error': 'Missing fields.'}), 400

    if len(new_password) < 6:
        return jsonify({'error': 'Password too short.'}), 400

    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    result = supabase.table('users').update({'password': hashed}).eq('id', user_id).execute()

    if result.data:
        return jsonify({'message': 'Password updated.'}), 200
    else:
        return jsonify({'error': 'Failed to update password.'}), 500


# ─── Notes / Upload API ──────────────────────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload_file():
    semester = request.form.get('semester')
    title    = request.form.get('title', '').strip()
    user_id  = request.form.get('user_id')
    file     = request.files.get('noteFile')

    if not all([semester, title, user_id, file]):
        return jsonify({'error': 'All fields are required.'}), 400

    # Generate a unique filename
    ext      = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"

    # Upload file to Supabase Storage bucket named "notes"
    file_bytes = file.read()
    storage_path = f"{user_id}/{filename}"

    try:
        supabase.storage.from_('notes').upload(storage_path, file_bytes, {
            'content-type': file.content_type
        })
    except Exception as e:
        return jsonify({'error': f'File upload failed: {str(e)}'}), 500

    # Get public URL
    public_url = supabase.storage.from_('notes').get_public_url(storage_path)

    # Get uploader name
    user_res = supabase.table('users').select('full_name').eq('id', user_id).execute()
    uploader_name = user_res.data[0]['full_name'] if user_res.data else 'Unknown'

    # Save metadata to notes table
    result = supabase.table('notes').insert({
        'title':         title,
        'semester':      semester,
        'file_url':      public_url,
        'storage_path':  storage_path,
        'user_id':       user_id,
        'uploader_name': uploader_name,
        'created_at':    datetime.utcnow().isoformat()
    }).execute()

    if result.data:
        return jsonify({'message': 'Uploaded successfully!', 'file_url': public_url}), 200
    else:
        return jsonify({'error': 'Failed to save note metadata.'}), 500


@app.route('/api/get_all_notes', methods=['GET'])
def get_all_notes():
    result = supabase.table('notes').select('*').order('created_at', desc=True).execute()
    return jsonify(result.data or [])


@app.route('/api/get_my_uploads', methods=['GET'])
def get_my_uploads():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    result = supabase.table('notes').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
    return jsonify(result.data or [])


@app.route('/api/delete_note', methods=['POST'])
def delete_note():
    data    = request.get_json()
    note_id = data.get('id')
    user_id = data.get('user_id')

    if not note_id or not user_id:
        return jsonify({'error': 'Missing fields.'}), 400

    # Fetch note to verify ownership and get storage path
    note_res = supabase.table('notes').select('*').eq('id', note_id).eq('user_id', user_id).execute()
    if not note_res.data:
        return jsonify({'error': 'Note not found or permission denied.'}), 404

    note = note_res.data[0]

    # Delete from storage
    try:
        supabase.storage.from_('notes').remove([note['storage_path']])
    except Exception:
        pass  # Continue even if storage delete fails

    # Delete from table
    supabase.table('notes').delete().eq('id', note_id).execute()

    return jsonify({'message': 'Deleted successfully.'}), 200


@app.route('/search-notes', methods=['GET'])
def search_notes():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    # Search by title (case-insensitive)
    result = supabase.table('notes').select('*').ilike('title', f'%{q}%').execute()
    return jsonify(result.data or [])


@app.route('/api/get_stats', methods=['GET'])
def get_stats():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'uploads': 0, 'downloads': 0})

    result = supabase.table('notes').select('id').eq('user_id', user_id).execute()
    uploads = len(result.data) if result.data else 0

    return jsonify({'uploads': uploads, 'downloads': 0})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
