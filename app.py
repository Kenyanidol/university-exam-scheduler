from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from datetime import datetime

load_dotenv("system.env")  

import os
from flask import Flask, flash, redirect, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_exam_portal_key_2026")

# Database URI configuration...

# Configure PostgreSQL connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://carlos:carlos_secure_password@localhost:5432/exam_scheduler_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class UserModel(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    identifier = db.Column(db.String(50), unique=True, nullable=False)  # Admission No or Lecturer Service No
    role = db.Column(db.String(20), nullable=False)                     # 'student', 'lecturer', 'admin'
    password = db.Column(db.String(200), nullable=False)
    is_first_login = db.Column(db.Boolean, default=True)


class ExamModel(db.Model):
  __tablename__ = "exams"

  id = db.Column(db.Integer, primary_key=True)
  course_code = db.Column(db.String(50), nullable=False)
  venue = db.Column(db.String(100), nullable=False)
  start_time = db.Column(db.String(100), nullable=False)
  end_time = db.Column(db.String(100), nullable=False)
  venue_capacity = db.Column(db.Integer, nullable=False)
  enrolled_students = db.Column(db.Text, nullable=True)
  invigilator = db.Column(
      db.String(100), nullable=True
  ) 

class BackupModel(db.Model):
    __tablename__ = 'backups'
    id = db.Column(db.Integer, primary_key=True)
    backup_id = db.Column(db.String(50), unique=True, nullable=False)
    backup_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    filename = db.Column(db.String(255), nullable=False)
    recovery_point = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)  # 'Success' or 'Failed'


# --- CONFLICT DETECTION ENGINE ---
class ExamSchedulerEngine:
    def check_time_overlap(self, start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
        return max(start1, start2) < min(end1, end2)

    def validate_and_schedule(self, new_exam_data):
        existing_exams = ExamModel.query.all()
        
        conflicts = {
            "room_conflict": False,
            "student_clashes": [],
            "capacity_violation": False,
            "messages": []
        }

        new_students = set([s.strip() for s in new_exam_data['enrolled_students'].split(",") if s.strip()])

        if len(new_students) > new_exam_data['capacity']:
            conflicts["capacity_violation"] = True
            conflicts["messages"].append(
                f"Capacity exceeded for venue {new_exam_data['venue']}: {len(new_students)} students enrolled, but capacity is {new_exam_data['capacity']}."
            )

        for existing in existing_exams:
            if self.check_time_overlap(new_exam_data['start_time'], new_exam_data['end_time'], existing.start_time, existing.end_time):
                if new_exam_data['venue'] == existing.venue:
                    conflicts["room_conflict"] = True
                    conflicts["messages"].append(
                        f"Room conflict: Venue '{new_exam_data['venue']}' is already booked by {existing.course_code} during this time."
                    )

                existing_students = set([s.strip() for s in existing.enrolled_students.split(",") if s.strip()])
                common_students = new_students.intersection(existing_students)
                if common_students:
                    conflicts["student_clashes"].extend(list(common_students))
                    conflicts["messages"].append(
                        f"Student clash: {len(common_students)} student(s) have overlapping exams between {new_exam_data['course_code']} and {existing.course_code}."
                    )

        is_valid = not (conflicts["room_conflict"] or conflicts["capacity_violation"] or len(conflicts["student_clashes"]) > 0)
        
        if is_valid:
            db.session.add(ExamModel(**new_exam_data))
            db.session.commit()
            return {"success": True, "message": f"Successfully scheduled {new_exam_data['course_code']} in {new_exam_data['venue']}!"}
        else:
            return {"success": False, "conflicts": conflicts["messages"]}

scheduler_engine = ExamSchedulerEngine()

scheduler_engine = ExamSchedulerEngine()

# ADD BACKUP MANAGER:
import os
import subprocess

class BackupRecoveryManager:
    def __init__(self, backup_dir="backups"):
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_backup(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"BK_{timestamp}"
        filename = f"exam_scheduler_backup_{timestamp}.sql"
        filepath = os.path.join(self.backup_dir, filename)

        cmd = [
            "pg_dump",
            "-h", "localhost",
            "-U", "carlos",
            "-d", "exam_scheduler_db",
            "-F", "p",
            "-f", filepath
        ]

        env = os.environ.copy()
        env["PGPASSWORD"] = "carlos_secure_password"

        try:
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            backup_record = BackupModel(
                backup_id=backup_id,
                filename=filename,
                recovery_point=filepath,
                status="Success"
            )
            db.session.add(backup_record)
            db.session.commit()
            
            return {"success": True, "message": f"Backup {backup_id} created successfully."}
        except subprocess.CalledProcessError as e:
            return {"success": False, "message": f"Backup failed: {e.stderr.decode()}"}

    def restore_backup(self, filepath):
        if not os.path.exists(filepath):
            return {"success": False, "message": "Backup file not found."}

        cmd = [
            "psql",
            "-h", "localhost",
            "-U", "carlos",
            "-d", "exam_scheduler_db",
            "-f", filepath
        ]

        env = os.environ.copy()
        env["PGPASSWORD"] = "carlos_secure_password"

        try:
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return {"success": True, "message": "Database restored successfully from recovery point."}
        except subprocess.CalledProcessError as e:
            return {"success": False, "message": f"Restore failed: {e.stderr.decode()}"}

backup_manager = BackupRecoveryManager()

# --- INITIALIZE DATABASE TABLES & SEED USERS ---
with app.app_context():
  db.create_all()

  admin_id = os.getenv("ADM-001")  # Should be ADM-001
  admin_pass = os.getenv("SecureAdminPassword123")  # Should be SecureAdminPassword123

  # Check if admin exists
  existing_admin = UserModel.query.filter_by(identifier=admin_id).first()

  if not existing_admin and admin_id and admin_pass:
    admin_user = UserModel(
        identifier=admin_id,
        name="System Administrator",
        password=admin_pass,  # 👈 Storing in plain text temporarily for testing
        role="admin",
        is_first_login=False,
    )
    db.session.add(admin_user)
    db.session.commit()
    print("Simple admin seeded in plain text!")
  else:
    print("Admin already exists.")

# --- ROUTES ---
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
  if request.method == "POST":
    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "").strip()

    user = UserModel.query.filter_by(identifier=identifier).first()

    if user and check_password_hash(user.password, password):
      
      session["user"] = user.identifier
      session["role"] = user.role.lower()  # Stores 'admin', 'lecturer', 'student'
      session["name"] = user.name

      if user.is_first_login:
        return redirect(url_for("update_password"))

      return redirect(url_for("dashboard"))
    else:
      flash("Invalid credentials", "danger")

  return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
  if request.method == "POST":
    identifier = request.form.get("identifier", "").strip()
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "student").strip()  # 'student' or 'lecturer'

    # Check if user already exists
    existing_user = UserModel.query.filter_by(identifier=identifier).first()
    if existing_user:
      flash("Identifier already registered. Please log in.", "danger")
      return redirect(url_for("register"))

    hashed_pw = generate_password_hash(identifier)

    new_user = UserModel(
        identifier=identifier,
        name=name,
        password=hashed_pw,
        role=role,
        is_first_login=True,  # 👈 Triggers first-time login check
    )
    db.session.add(new_user)
    db.session.commit()

    flash(
        "Account created! Your initial password is your admission number.",
        "success",
    )
    return redirect(url_for("login"))

  return render_template("register.html")

@app.route("/update-password", methods=["GET", "POST"])
def update_password():
  if "user" not in session:
    return redirect(url_for("login"))

  user = UserModel.query.filter_by(identifier=session["user"]).first()

  if request.method == "POST":
    # Check if they clicked the "Skip" button
    if "skip" in request.form:
      user.is_first_login = False
      db.session.commit()
      return redirect(url_for("dashboard"))

    # Otherwise, handle normal password update
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    if new_password != confirm_password:
      flash("Passwords do not match.", "danger")
      return redirect(url_for("update_password"))

    user.password = generate_password_hash(new_password)
    user.is_first_login = False  # Mark first login as done
    db.session.commit()

    flash("Password updated successfully!", "success")
    return redirect(url_for("dashboard"))

  return render_template("update_password.html", user=user)

    # View all users (Students & Lecturers)
@app.route("/admin/users")
def manage_users():
  if "user" not in session or session["role"] != "admin":
    flash("Unauthorized access.", "error")
    return redirect(url_for("dashboard"))

  users = UserModel.query.all()
  return render_template("manage_users.html", users=users)


# Edit a specific user's real-time details
@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
  if "user" not in session or session["role"] != "admin":
    flash("Unauthorized access.", "error")
    return redirect(url_for("dashboard"))

  user = UserModel.query.get_or_404(user_id)

  if request.method == "POST":
    # Capture updated real-time form data
    user.name = request.form.get("name")
    user.identifier = request.form.get("identifier")  # Adm No or Service No
    user.role = request.form.get("role")  # student, lecturer, or admin

    db.session.commit()
    flash(
        f"Details for {user.name} updated successfully in real-time.",
        "success",
    )
    return redirect(url_for("manage_users"))

  return render_template("edit_user.html", user=user)

@app.route("/lecturer/exam/edit/<int:exam_id>", methods=["GET", "POST"])
def edit_exam_record(exam_id):
    if "user" not in session or session["role"] not in ["admin", "lecturer"]:
        flash("Unauthorized access.", "error")
        return redirect(url_for("dashboard"))

    exam = ExamModel.query.get_or_404(exam_id)
    current_user = UserModel.query.filter_by(identifier=session["user"]).first()

    #  Ownership Security Check:
    if session["role"] == "lecturer" and exam.lecturer_id != current_user.id:
        flash("You do not have permission to edit exams assigned to other lecturers.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        #  Capture and apply updated scheduling details
        exam.course_code = request.form.get("course_code")
        exam.course_name = request.form.get("course_name")
        exam.student_group = request.form.get("student_group")
        exam.venue = request.form.get("venue")
        
        # Re-run your conflict-detection engine here if date/venue changes!
        # clash_detected = scheduler_engine.check_clashes(exam.date_time, exam.venue)

        db.session.commit()
        flash("Exam schedule updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_exam.html", exam=exam)

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
  if "user" not in session:
    return redirect(url_for("login"))

  # Fetch all lecturers for the invigilator dropdown
  lecturers = UserModel.query.filter_by(role="lecturer").all()

  if request.method == "POST" and session.get("role") == "admin":
    # Handle Exam Scheduling with Invigilator
    course_code = request.form.get("course_code")
    venue = request.form.get("venue")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    venue_capacity = int(request.form.get("venue_capacity", 100))
    enrolled_students = request.form.get("enrolled_students")
    invigilator = request.form.get("invigilator")  # Selected lecturer

    existing_exams = ExamModel.query.filter_by(venue=venue).all()
    for ex in existing_exams:
      # Overlap condition: (StartA < EndB) and (EndA > StartB)
      if start_time < ex.end_time and end_time > ex.start_time:
        flash(
            f"❌ Conflict Error: Venue '{venue}' is already booked for"
            f" {ex.course_code} from {ex.start_time} to {ex.end_time}!",
            "danger",
        )
        return redirect(url_for("dashboard"))

    new_exam = ExamModel(
        course_code=course_code,
        venue=venue,
        start_time=start_time,
        end_time=end_time,
        venue_capacity=venue_capacity,
        enrolled_students=enrolled_students,
        invigilator=invigilator,
    )
    db.session.add(new_exam)
    db.session.commit()
    flash("Exam scheduled and invigilator assigned successfully!", "success")
    return redirect(url_for("dashboard"))

  # Fetch exams based on role
  if session.get("role") == "admin":
    exams = ExamModel.query.all()
  elif session.get("role") == "lecturer":
    # Lecturers only see exams where they are assigned as the invigilator
    current_user_name = session.get("name")
    exams = ExamModel.query.filter_by(invigilator=current_user_name).all()
  else:
    # Students view
    exams = ExamModel.query.all()

  return render_template("dashboard.html", exams=exams, lecturers=lecturers)

  import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

@app.route("/delete-exam/<int:exam_id>", methods=["POST"])
def delete_exam(exam_id):
  if session.get("role") != "admin":
    flash("Unauthorized action.", "danger")
    return redirect(url_for("dashboard"))

  exam = ExamModel.query.get_or_404(exam_id)
  db.session.delete(exam)
  db.session.commit()
  flash("Exam schedule deleted successfully.", "success")
  return redirect(url_for("dashboard"))


@app.route("/upload-file", methods=["POST"])
def upload_file():
  if session.get("role") != "admin":
    flash("Unauthorized action.", "danger")
    return redirect(url_for("dashboard"))

  if "file" in request.files:
    file = request.files["file"]
    if file.filename != "":
      filename = secure_filename(file.filename)
      file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
      flash(f"File '{filename}' uploaded successfully!", "success")

  return redirect(url_for("dashboard"))

@app.route("/schedule", methods=["POST"])
def schedule():
    if "user" not in session or session["role"] != "admin":
        flash("Unauthorized action.", "error")
        return redirect(url_for("dashboard"))

    try:
        exam_data = {
            "exam_id": f"E_{ExamModel.query.count() + 1}",
            "course_code": request.form.get("course_code"),
            "venue": request.form.get("venue"),
            "start_time": datetime.strptime(request.form.get("start_time"), "%Y-%m-%dT%H:%M"),
            "end_time": datetime.strptime(request.form.get("end_time"), "%Y-%m-%dT%H:%M"),
            "capacity": int(request.form.get("capacity")),
            "enrolled_students": request.form.get("students")
        }

        result = scheduler_engine.validate_and_schedule(exam_data)
        if result["success"]:
            flash(result["message"], "success")
        else:
            for err in result["conflicts"]:
                flash(err, "error")

    except Exception as e:
        flash(f"Error scheduling exam: {str(e)}", "error")

    return redirect(url_for("dashboard"))

@app.route("/admin/backup", methods=["POST"])
def trigger_backup():
    if "user" not in session or session["role"] != "admin":
        flash("Unauthorized access.", "error")
        return redirect(url_for("dashboard"))

    result = backup_manager.create_backup()
    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")
    
    return redirect(url_for("dashboard"))

@app.route("/admin/restore/<int:backup_id>", methods=["POST"])
def trigger_restore(backup_id):
    if "user" not in session or session["role"] != "admin":
        flash("Unauthorized access.", "error")
        return redirect(url_for("dashboard"))

    backup = BackupModel.query.get_or_404(backup_id)
    result = backup_manager.restore_backup(backup.recovery_point)
    
    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")
        
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("login"))


with app.app_context():
    db.create_all()

    # Seed default admin if none exists
    if not UserModel.query.filter_by(role="admin").first():
        admin_identifier = os.getenv("ADMIN_IDENTIFIER", "ADMIN_DEFAULT")
        admin_name = os.getenv("ADMIN_NAME", "Administrator")
        admin_raw_password = os.getenv("ADMIN_PASSWORD", "changeme")

        hashed_password = generate_password_hash(admin_raw_password)

        initial_admin = UserModel(
            identifier=admin_identifier,
            name=admin_name,
            password=hashed_password,
            role="admin",
            is_first_login=True,
        )
        db.session.add(initial_admin)
        db.session.commit()
        print("Default administrator created securely from environment variables.")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
