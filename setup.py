# setup_notifications.py - RUN THIS ONCE
import os
import subprocess

print("🚀 Setting up LoveUAD notification system...")
print("=" * 50)

# 1. Install required package
print("\n📦 Installing APScheduler...")
subprocess.run(["pip", "install", "apscheduler"], check=True)

# 2. Add to app.py
app_py_code = '''

# ============ NOTIFICATION SYSTEM ============
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time as dt_time

scheduler = BackgroundScheduler()
scheduler.start()

# Store active alarms in memory
active_alarms = {}

@app.route("/api/medications/save", methods=["POST"])
def save_medication_with_alarms():
    """Save medication and set alarms"""
    data = request.json
    code_hash = data.get('codeHash')
    
    medication = {
        'codeHash': code_hash,
        'name': data.get('name'),
        'dosage': data.get('dosage'),
        'times': data.get('times'),
        'createdAt': datetime.utcnow()
    }
    
    result = medications_collection.insert_one(medication)
    med_id = str(result.inserted_id)
    
    # Schedule alarms for each time
    for time_str in medication['times']:
        hour, minute = map(int, time_str.split(':'))
        job_id = f"{code_hash}_{med_id}_{time_str}"
        
        scheduler.add_job(
            func=trigger_alarm,
            trigger='cron',
            hour=hour,
            minute=minute,
            args=[code_hash, medication['name'], medication['dosage'], time_str],
            id=job_id,
            replace_existing=True
        )
        active_alarms[job_id] = {'medication': medication['name'], 'time': time_str}
    
    return jsonify({'success': True, 'medicationId': med_id})

def trigger_alarm(code_hash, med_name, dosage, time_str):
    """Triggered when alarm time is reached"""
    print(f"\\n🔔 ALARM: {med_name} ({dosage}) at {time_str}")
    
    # Store pending alarm in database
    pending_alarms_collection.insert_one({
        'codeHash': code_hash,
        'medicationName': med_name,
        'dosage': dosage,
        'time': time_str,
        'triggeredAt': datetime.utcnow(),
        'acknowledged': False
    })

@app.route("/api/alarms/pending/<code_hash>", methods=["GET"])
def get_pending_alarms(code_hash):
    """Get alarms that haven't been acknowledged"""
    alarms = list(pending_alarms_collection.find({
        'codeHash': code_hash,
        'acknowledged': False
    }))
    
    for alarm in alarms:
        alarm['_id'] = str(alarm['_id'])
    
    return jsonify({'success': True, 'alarms': alarms})

@app.route("/api/alarms/acknowledge", methods=["POST"])
def acknowledge_alarm():
    """Mark alarm as seen"""
    data = request.json
    alarm_id = data.get('alarmId')
    
    pending_alarms_collection.update_one(
        {'_id': ObjectId(alarm_id)},
        {'$set': {'acknowledged': True, 'acknowledgedAt': datetime.utcnow()}}
    )
    
    return jsonify({'success': True})

# ============ ALL ROUTES ============
@app.route("/caregiver-reminders.html", methods=["GET"])
def caregiver_reminders_page():
    return render_template("caregiver-reminders.html")

@app.route("/caregiver-health.html", methods=["GET"])
def caregiver_health_page():
    return render_template("caregiver-health.html")

@app.route("/caregiver-chat.html", methods=["GET"])
def caregiver_chat_page():
    return render_template("caregiver-chat.html")

@app.route("/caregiver-dashboard.html", methods=["GET"])
def caregiver_dashboard_page():
    return render_template("caregiver-dashboard.html")

@app.route("/caregiver-medicines.html", methods=["GET"])
def caregiver_medicines_page():
    return render_template("caregiver-medicines.html")

@app.route("/caregiver-login.html", methods=["GET"])
def caregiver_login_page():
    return render_template("caregiver-login.html")

@app.route("/patient-dashboard.html", methods=["GET"])
def patient_dashboard_page():
    return render_template("patient-dashboard.html")

@app.route("/patient-reminders.html", methods=["GET"])
def patient_reminders_page():
    return render_template("patient-reminders.html")

@app.route("/patient-medicines.html", methods=["GET"])
def patient_medicines_page():
    return render_template("patient-medicines.html")

@app.route("/patient-login.html", methods=["GET"])
def patient_login_page():
    return render_template("patient-login.html")

@app.route("/patient-register.html", methods=["GET"])
def patient_register_page():
    return render_template("patient-register.html")

@app.route("/patient-camera.html", methods=["GET"])
def patient_camera_page():
    return render_template("patient-camera.html")

@app.route("/patient-settings.html", methods=["GET"])
def patient_settings_page():
    return render_template("patient-settings.html")

@app.route("/role-selection.html", methods=["GET"])
def role_selection_page():
    return render_template("role-selection.html")

@app.route("/dashboard.html", methods=["GET"])
def dashboard_page():
    return render_template("dashboard.html")
'''

# 3. Append to app.py
print("\n📝 Adding code to app.py...")
with open("app.py", "a", encoding="utf-8") as f:
    f.write(app_py_code)

# 4. Create MongoDB collection name in app.py
print("\n💾 Adding database collection...")
db_code = '''
# Add after your other collection definitions
pending_alarms_collection = db['pending_alarms']
'''

with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

if "pending_alarms_collection" not in content:
    # Find where medications_collection is defined and add after it
    with open("app.py", "a", encoding="utf-8") as f:
        f.write(db_code)

print("\n✅ DONE! Setup complete!")
print("\n" + "=" * 50)
print("📋 What was added:")
print("  ✓ APScheduler installed")
print("  ✓ Alarm scheduling system")
print("  ✓ All page routes")
print("  ✓ Pending alarms API")
print("\n🚀 Just restart your Flask app now!")
print("=" * 50)