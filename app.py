import os
import mimetypes
import cloudinary
import cloudinary.uploader
import cloudinary.api
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from sqlalchemy import inspect, text

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if DATABASE_URL:
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, 'bayune_maths.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bayune-lhs-maths-secure-key-2026')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'), exist_ok=True)
STATIC_MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'resources')
os.makedirs(STATIC_MEDIA_DIR, exist_ok=True)

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
    app.config['CLOUDINARY_ENABLED'] = True
else:
    app.config['CLOUDINARY_ENABLED'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'teachers'

@app.after_request
def disable_cache(response):
    if 'text/html' in response.content_type or '/api/' in request.path:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

ALLOWED_EXTENSIONS = {'pdf', 'csv', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'ppt', 'pptx'}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), default='viewer')
    full_name = db.Column(db.String(100), default='')
    position = db.Column(db.String(50), default='')
    profile_image = db.Column(db.String(500), default='')

class Update(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author = db.relationship('User')

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grade = db.Column(db.String(50), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    saved_filename = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploader = db.relationship('User')

class TeacherAid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    file_type = db.Column(db.String(50), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    saved_filename = db.Column(db.String(200), default='')
    url = db.Column(db.String(300), default='')
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploader = db.relationship('User')

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    class_name = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS

def seed_database():
    with app.app_context():
        db.create_all()
        try:
            inspector = inspect(db.engine)
            if 'user' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('user')]
                if 'profile_image' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE \"user\" ADD COLUMN profile_image VARCHAR(500) DEFAULT ''"))
                        conn.commit()
            if 'comment' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('comment')]
                if 'email' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE comment ADD COLUMN email VARCHAR(150) DEFAULT ''"))
                        conn.commit()
                if 'phone' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE comment ADD COLUMN phone VARCHAR(50) DEFAULT ''"))
                        conn.commit()
        except Exception as e:
            app.logger.error(f"Migration warning: {e}")

seed_database()

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static-media/<path:filename>')
def stream_static_media(filename):
    return send_from_directory(STATIC_MEDIA_DIR, filename, mimetype=mimetypes.guess_type(filename)[0] or 'application/octet-stream')

@app.route('/manifest.json')
def serve_manifest(): return send_from_directory('static', 'manifest.json', mimetype='application/json')

@app.route('/sw.js')
def serve_sw(): return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml', mimetype='application/xml')

@app.route('/robots.txt')
def robots(): return send_from_directory('static', 'robots.txt', mimetype='text/plain')

@app.route('/')
def home(): return render_template('index.html', page='home')

@app.route('/updates')
def updates():
    all_updates = Update.query.order_by(Update.created_at.desc()).all()
    return render_template('index.html', page='updates', updates=all_updates)

@app.route('/students')
def students():
    resources = Resource.query.order_by(Resource.uploaded_at.desc()).all()
    return render_template('index.html', page='students', resources=resources)

@app.route('/teachers')
def teachers():
    teacher_list = User.query.filter_by(role='teacher').all()
    aids = TeacherAid.query.order_by(TeacherAid.uploaded_at.desc()).all()
    return render_template('index.html', page='teachers', teachers=teacher_list, aids=aids)

@app.route('/about')
def about():
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template('index.html', page='about', comments=comments)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Successfully logged in.')
            return redirect(url_for('teachers'))
        flash('Invalid username or password.')
    return redirect(url_for('teachers'))

@app.route('/logout')
def logout():
    logout_user()
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('home'))

@app.route('/api/teachers/register', methods=['POST'])
def register_teacher():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    full_name = request.form.get('full_name', '').strip()
    position = request.form.get('position', '').strip()
    school_code = request.form.get('school_code', '').strip()

    if school_code != 'BLSS2026':
        flash('Invalid School Registration Code. Please contact the HOD.')
        return redirect(url_for('teachers'))

    if not username or not password or not full_name or not position:
        flash('All fields are required.')
        return redirect(url_for('teachers'))

    if User.query.filter_by(username=username).first():
        flash('Username already exists. Please choose another.')
        return redirect(url_for('teachers'))

    new_teacher = User(
        username=username,
        password_hash=generate_password_hash(password),
        role='teacher',
        full_name=full_name,
        position=position
    )
    db.session.add(new_teacher)
    db.session.commit()
    flash('Registration successful! Please log in with your new credentials.')
    return redirect(url_for('teachers'))

@app.route('/api/teacher/profile', methods=['POST'])
@login_required
def update_teacher_profile():
    if current_user.role != 'teacher': abort(403)
    try:
        current_user.full_name = request.form.get('full_name', '').strip()
        current_user.position = request.form.get('position', '').strip()
        file = request.files.get('profile_image')
        if file and file.filename and file.filename != '':
            if not allowed_image(file.filename):
                flash('Invalid file type. Use JPG, PNG, or GIF only.')
                return redirect(url_for('teachers'))
            if app.config.get('CLOUDINARY_ENABLED'):
                upload_result = cloudinary.uploader.upload(
                    file, folder='bayune_teachers', public_id=f"prof_{current_user.id}",
                    overwrite=True, resource_type='image',
                    transformation=[{'width': 400, 'height': 400, 'crop': 'thumb', 'gravity': 'face'}, {'quality': 'auto', 'fetch_format': 'auto'}]
                )
                current_user.profile_image = upload_result['secure_url']
            else:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                filename = secure_filename(f"prof_{current_user.id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.profile_image = filename
        db.session.commit()
        flash('Profile updated successfully.')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating profile: {str(e)}')
    return redirect(url_for('teachers'))

@app.route('/hod-dashboard')
@login_required
def hod_dashboard():
    if 'hod' not in current_user.position.lower():
        abort(403)
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('index.html', page='hod', teachers=teachers)

@app.route('/api/hod/reset-password/<int:user_id>', methods=['POST'])
@login_required
def hod_reset_password(user_id):
    if 'hod' not in current_user.position.lower():
        abort(403)
    user = db.session.get(User, user_id)
    if user and user.role == 'teacher':
        new_pw = request.form.get('new_password', 'BLSS2026')
        user.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash(f'Password for {user.username} reset to: {new_pw}')
    return redirect(url_for('hod_dashboard'))

@app.route('/api/hod/update-username/<int:user_id>', methods=['POST'])
@login_required
def hod_update_username(user_id):
    if 'hod' not in current_user.position.lower():
        abort(403)
    user = db.session.get(User, user_id)
    if user and user.role == 'teacher':
        new_username = request.form.get('new_username', '').strip()
        if new_username and not User.query.filter_by(username=new_username).first():
            user.username = new_username
            db.session.commit()
            flash(f'Username updated to: {new_username}')
        else:
            flash('Username already exists or is invalid.')
    return redirect(url_for('hod_dashboard'))

@app.route('/api/hod/delete-user/<int:user_id>', methods=['POST'])
@login_required
def hod_delete_user(user_id):
    if 'hod' not in current_user.position.lower():
        abort(403)
    
    user = db.session.get(User, user_id)
    if user and user.role == 'teacher':
        if user.id == current_user.id:
            flash('You cannot delete your own account.')
        else:
            try:
                Resource.query.filter_by(uploader_id=user.id).delete()
                TeacherAid.query.filter_by(uploader_id=user.id).delete()
                Update.query.filter_by(author_id=user.id).delete()
                
                db.session.delete(user)
                db.session.commit()
                flash(f'Teacher profile for {user.full_name} has been permanently deleted.')
            except Exception as e:
                db.session.rollback()
                flash(f'Error deleting user: {str(e)}')
    
    return redirect(url_for('hod_dashboard'))

@app.route('/api/comments', methods=['POST'])
def submit_comment():
    full_name = request.form.get('full_name')
    status = request.form.get('status')
    class_name = request.form.get('class_name')
    email = (request.form.get('email') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    content = (request.form.get('content') or '').strip()
    if not email and not phone:
        flash('Please provide a valid Email or Phone Number.')
        return redirect(url_for('about'))
    if status == 'Student' and not class_name:
        flash('Students must select their Class.')
        return redirect(url_for('about'))
    if not content or len(content.split()) > 255:
        flash('Comment must be between 1 and 255 words.')
        return redirect(url_for('about'))
    db.session.add(Comment(full_name=full_name, status=status, class_name=class_name if status == 'Student' else None, email=email, phone=phone, content=content))
    db.session.commit()
    flash('Thank you! Your comment/query has been submitted.')
    return redirect(url_for('about'))

@app.route('/api/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    if current_user.role != 'teacher': abort(403)
    comment = db.session.get(Comment, comment_id)
    if comment:
        db.session.delete(comment)
        db.session.commit()
        flash('Comment deleted.')
    return redirect(url_for('about'))

@app.route('/api/updates', methods=['POST'])
@login_required
def post_update():
    if current_user.role != 'teacher': abort(403)
    title, content = request.form.get('title'), request.form.get('content')
    if title and content:
        db.session.add(Update(title=title, content=content, author=current_user))
        db.session.commit()
        flash('Update published.')
    return redirect(url_for('updates'))

@app.route('/api/updates/<int:update_id>/edit', methods=['POST'])
@login_required
def edit_update(update_id):
    if current_user.role != 'teacher': abort(403)
    update = db.session.get(Update, update_id)
    if update:
        update.title = request.form.get('title')
        update.content = request.form.get('content')
        db.session.commit()
        flash('Update edited.')
    return redirect(url_for('updates'))

@app.route('/api/updates/<int:update_id>/delete', methods=['POST'])
@login_required
def delete_update(update_id):
    if current_user.role != 'teacher': abort(403)
    update = db.session.get(Update, update_id)
    if update:
        db.session.delete(update)
        db.session.commit()
        flash('Update deleted.')
    return redirect(url_for('updates'))

@app.route('/api/resources', methods=['POST'])
@login_required
def upload_resource():
    if current_user.role != 'teacher': abort(403)
    grade, file = request.form.get('grade'), request.files.get('file')
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        db.session.add(Resource(grade=grade, original_filename=filename, saved_filename=unique_filename, file_type=ext, uploader=current_user))
        db.session.commit()
        flash('Resource uploaded.')
    return redirect(url_for('students'))

@app.route('/api/resources/register-static', methods=['POST'])
@login_required
def register_static_resource():
    if current_user.role != 'teacher': abort(403)
    grade, filename = request.form.get('grade'), secure_filename(request.form.get('filename'))
    if not filename or not os.path.exists(os.path.join(STATIC_MEDIA_DIR, filename)):
        flash('File not found in static/resources/.')
        return redirect(url_for('students'))
    ext = filename.rsplit('.', 1)[1].lower()
    db.session.add(Resource(grade=grade, original_filename=filename, saved_filename=f"static:{filename}", file_type=ext, uploader=current_user))
    db.session.commit()
    flash('Static resource registered.')
    return redirect(url_for('students'))

@app.route('/api/resources/<int:res_id>/preview')
def preview_resource(res_id):
    res = db.session.get(Resource, res_id)
    if not res: abort(404)
    mime = mimetypes.guess_type(res.original_filename)[0] or 'application/octet-stream'
    path = STATIC_MEDIA_DIR if res.saved_filename.startswith('static:') else app.config['UPLOAD_FOLDER']
    filename = res.saved_filename[7:] if res.saved_filename.startswith('static:') else res.saved_filename
    return send_from_directory(path, filename, mimetype=mime)

@app.route('/api/resources/<int:res_id>/download')
def download_resource(res_id):
    res = db.session.get(Resource, res_id)
    if not res: abort(404)
    path = STATIC_MEDIA_DIR if res.saved_filename.startswith('static:') else app.config['UPLOAD_FOLDER']
    filename = res.saved_filename[7:] if res.saved_filename.startswith('static:') else res.saved_filename
    return send_from_directory(path, filename, as_attachment=True, download_name=res.original_filename)

@app.route('/api/resources/<int:res_id>/delete', methods=['POST'])
@login_required
def delete_resource(res_id):
    if current_user.role != 'teacher': abort(403)
    res = db.session.get(Resource, res_id)
    if res:
        if not res.saved_filename.startswith('static:'):
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], res.saved_filename)
            if os.path.exists(fpath): os.remove(fpath)
        db.session.delete(res)
        db.session.commit()
        flash('Resource deleted.')
    return redirect(url_for('students'))

@app.route('/api/teacher-aids', methods=['POST'])
@login_required
def upload_teacher_aid():
    if current_user.role != 'teacher': abort(403)
    title, desc, url = request.form.get('title'), request.form.get('description',''), request.form.get('url','')
    aid = TeacherAid(title=title, description=desc, uploader=current_user)
    file = request.files.get('file')
    if file and file.filename != '' and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        unique_filename = f"aid_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        aid.saved_filename = unique_filename
        aid.original_filename = filename
        aid.file_type = ext
    elif url:
        aid.file_type = 'website'
        aid.url = url
    else:
        flash('Provide file or URL.')
        return redirect(url_for('teachers'))
    db.session.add(aid)
    db.session.commit()
    flash('Aid added.')
    return redirect(url_for('teachers'))

@app.route('/api/teacher-aids/register-static', methods=['POST'])
@login_required
def register_static_aid():
    if current_user.role != 'teacher': abort(403)
    title, desc = request.form.get('title'), request.form.get('description','')
    filename = secure_filename(request.form.get('filename'))
    if not filename or not os.path.exists(os.path.join(STATIC_MEDIA_DIR, filename)):
        flash('File not found in static/resources/.')
        return redirect(url_for('teachers'))
    ext = filename.rsplit('.', 1)[1].lower()
    aid = TeacherAid(title=title, description=desc, file_type=ext, original_filename=filename, saved_filename=f"static:{filename}", uploader=current_user)
    db.session.add(aid)
    db.session.commit()
    flash('Static aid registered.')
    return redirect(url_for('teachers'))

@app.route('/api/teacher-aids/<int:aid_id>/download')
def download_aid(aid_id):
    aid = db.session.get(TeacherAid, aid_id)
    if not aid: abort(404)
    if aid.url: return redirect(aid.url)
    if aid.saved_filename:
        path = STATIC_MEDIA_DIR if aid.saved_filename.startswith('static:') else app.config['UPLOAD_FOLDER']
        filename = aid.saved_filename[7:] if aid.saved_filename.startswith('static:') else aid.saved_filename
        mime = mimetypes.guess_type(aid.original_filename)[0] or 'application/octet-stream'
        return send_from_directory(path, filename, mimetype=mime, as_attachment=True, download_name=aid.original_filename)
    abort(404)

@app.route('/api/teacher-aids/<int:aid_id>/delete', methods=['POST'])
@login_required
def delete_aid(aid_id):
    if current_user.role != 'teacher': abort(403)
    aid = db.session.get(TeacherAid, aid_id)
    if aid:
        if not aid.saved_filename.startswith('static:') and aid.saved_filename:
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], aid.saved_filename)
            if os.path.exists(fpath): os.remove(fpath)
        db.session.delete(aid)
        db.session.commit()
        flash('Aid deleted.')
    return redirect(url_for('teachers'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
