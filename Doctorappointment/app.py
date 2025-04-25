from flask import Flask, render_template, request, redirect, url_for, session, current_app
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from bson.objectid import ObjectId
import razorpay

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'secretkey'  # Secret key for session management

# MongoDB config
app.config["MONGO_URI"] = "mongodb://localhost:27017/doctor_appointment"
mongo = PyMongo(app)

# File upload config
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf', 'doc', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Allowed file check
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Razorpay credentials
razorpay_client = razorpay.Client(auth=("rzp_test_89QWS8wjmBuCdb", "UUFw9uzrtS2JL4hSI250HNrE"))

# Helper functions
def get_appointments():
    return list(mongo.db.appointments.find({'email': session.get('user_email')}))

def get_doctors():
    return list(mongo.db.doctors.find())

# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    doctors = list(mongo.db.doctors.find())
    return render_template('about.html', doctors=doctors)

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        print(f"Name: {name}, Email: {email}, Message: {message}")
        return redirect(url_for('thank_you'))
    return render_template('contact.html')

@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        role = request.form['role']
        if mongo.db.users.find_one({'email': email}):
            return 'User already exists!'
        mongo.db.users.insert_one({'name': name, 'email': email, 'password': password, 'role': role})
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = mongo.db.users.find_one({'email': email})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['user_email'] = user['email']
            session['role'] = user['role']
            if user['role'] == 'doctor':
                return redirect(url_for('doctor_page'))
            else:
                return redirect(url_for('patient_page'))
        else:
            error = 'Invalid credentials, please try again.'
    return render_template('login.html', error=error)

@app.route('/doctor_page', methods=['GET', 'POST'])
def doctor_page():
    if 'user_id' not in session or session['role'] != 'doctor':
        return redirect(url_for('login'))

    if request.method == 'POST':
        file = request.files['scanner']
        filename = ''
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        doctor_data = {
            'doctor_name': request.form['doctor_name'],
            'experience': request.form['experience'],
            'specialization': request.form['specialization'],
            'time': request.form['time'],
            'date': request.form['date'],
            'contact': request.form['contact'],
            'fee': request.form['fee'],
            'zoom_link': request.form['zoom_link'],
            'scanner': filename,
            'designation': request.form['designation'],
            'email': session.get('user_email')
        }
        mongo.db.doctors.insert_one(doctor_data)
        return redirect(url_for('doctor_page'))

    doctors = list(mongo.db.doctors.find())
    doctor = mongo.db.doctors.find_one({'email': session.get('user_email')})
    if not doctor:
        appointments = []
    else:
        appointments_cursor = mongo.db.appointments.find({'doctor_id': ObjectId(doctor['_id'])})
        appointments = []
        for app in appointments_cursor:
            patient = mongo.db.users.find_one({'email': app['email']})
            appointments.append({
                '_id': str(app.get('_id')),
                'patient_name': patient.get('name', app.get('name', 'N/A')) if patient else app.get('name', 'N/A'),
                'appointment_date': app.get('date', 'N/A'),
                'doctor_name': doctor.get('doctor_name', 'N/A'),
                'patient_contact': app.get('contact', 'N/A'),
                'address': app.get('address', 'N/A'),
                'problem': app.get('problem', 'N/A'),
                'scanner': app.get('scanner', ''),
                'email': patient.get('email', app.get('email', 'N/A')) if patient else app.get('email', 'N/A'),
                'status': app.get('status', 'Pending'),
                'paid': app.get('paid', False)
            })
    return render_template('doctor_page.html', doctors=doctors, appointments=appointments)

@app.route('/patient_page', methods=['GET', 'POST'])
def patient_page():
    if 'user_id' not in session or session['role'] != 'patient':
        return redirect(url_for('login'))

    current_user = session.get('user_email')
    appointments = get_appointments()
    doctors = get_doctors()

    # Enrich appointments with doctor_name and doctor_specialization
    enriched_appointments = []
    for appt in appointments:
        doctor = mongo.db.doctors.find_one({'_id': appt.get('doctor_id')})
        appt['doctor_name'] = doctor.get('doctor_name') if doctor else ''
        appt['doctor_specialization'] = doctor.get('specialization') if doctor else ''
        enriched_appointments.append(appt)

    # Find latest accepted appointment for Razorpay
    latest_appointment = None
    for appt in reversed(enriched_appointments):
        if appt.get("status") == "Accepted":
            latest_appointment = appt
            break
    appointment_id = str(latest_appointment['_id']) if latest_appointment else ""

    if request.method == 'POST':
        filename = ''
        if 'scanner' in request.files:
            file = request.files['scanner']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        doctor_id = request.form['doctor_id']
        doctor = mongo.db.doctors.find_one({'_id': ObjectId(doctor_id)})
        appointment_date = doctor.get('date') if doctor else 'N/A'

        appointment_data = {
            'name': request.form['name'],
            'email': current_user,
            'contact': request.form['contact'],
            'address': request.form['address'],
            'scanner': filename,
            'problem': request.form['problem'],
            'doctor_id': ObjectId(doctor_id),
            'date': appointment_date,
            "status": "Pending"
        }
        mongo.db.appointments.insert_one(appointment_data)
        return redirect(url_for('patient_page'))

    accepted_appointments = list(mongo.db.appointments.find({
        'email': session.get('user_email'),
        'status': 'Accepted'
    }))
    accepted_doctor_ids = {str(app['doctor_id']) for app in accepted_appointments}

    return render_template("patient_page.html",
                           appointments=enriched_appointments,
                           doctors=doctors,
                           accepted_doctor_ids=accepted_doctor_ids,
                           razorpay_key_id="rzp_test_89QWS8wjmBuCdb",
                           latest_appointment_id=appointment_id,
                           current_user=current_user)

@app.route('/payment_success', methods=['POST'])
def payment_success():
    appointment_id = request.form.get('appointment_id')
    if not appointment_id:
        return "Invalid request: missing appointment ID", 400

    # Mark appointment as paid
    result = mongo.db.appointments.update_one(
        {'_id': ObjectId(appointment_id)},
        {'$set': {'paid': True}}
    )
    if result.matched_count == 0:
        return "Appointment not found", 404

    # Optionally, verify payment with Razorpay here

    return redirect(url_for('patient_page'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))
from flask import jsonify

@app.route('/update_appointment_status/<appointment_id>', methods=['POST'])
def update_appointment_status(appointment_id):
    # Retrieve appointment by ID
    appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
    if not appointment:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Appointment not found'}), 404
        else:
            return 'Appointment not found', 404

    # Get the new status from the form
    new_status = request.form.get('status')
    if new_status not in ['Accepted', 'Rejected', 'Hold']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Invalid status'}), 400
        else:
            return 'Invalid status', 400

    # Update the status of the appointment
    mongo.db.appointments.update_one(
        {'_id': ObjectId(appointment_id)},
        {'$set': {'status': new_status}}
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Status updated successfully'})
    else:
        return redirect(url_for('doctor_page'))  # Redirect back to doctor page after update

@app.route('/post_prescription/<appointment_id>', methods=['POST'])
def post_prescription(appointment_id):
    if 'user_id' not in session or session['role'] != 'doctor':
        return redirect(url_for('login'))

    prescription_text = request.form.get('prescription')
    if not prescription_text:
        return "Prescription text is required", 400

    try:
        result = mongo.db.appointments.update_one(
            {"_id": ObjectId(appointment_id)},
            {"$set": {"prescription": prescription_text}}
        )
        if result.matched_count == 0:
            return "Appointment not found", 404
    except Exception as e:
        return f"An error occurred: {str(e)}", 500

    return redirect(url_for('doctor_page'))

if __name__ == '__main__':
    app.run(host=0.0.0.0,port=500,debug=True)
