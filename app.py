import cv2
import cvzone
from cvzone.HandTrackingModule import HandDetector
import time
import logging
import pygame
import os
from datetime import datetime
from flask import Flask, render_template, Response, jsonify, request, send_from_directory
import sqlite3

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = "uploads"
app.config['SCREENSHOT_FOLDER'] = "screenshots"

# Initialize pygame for audio
pygame.mixer.init()
alarm_sound = pygame.mixer.Sound("alarm.mp3")

# Camera setup
cap = cv2.VideoCapture(0)
cap.set(3, 1280)
cap.set(4, 720)

# Check if camera opened successfully
if not cap.isOpened():
    logging.error("Camera not found! Check permissions or try another index.")

# Hand detector setup
detector = HandDetector(detectionCon=0.8, maxHands=1)
alert_active = False
last_alert_time = 0
last_screenshot_path = None  # Store the last captured screenshot path
gesture_detected = False  # Flag to track detection status

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def is_distress_signal(hand):
    fingers = detector.fingersUp(hand)
    lmList = hand["lmList"]
    thumb_tip = lmList[4]
    thumb_mcp = lmList[2]

    if hand["type"] == "Right":
        return thumb_tip[0] < thumb_mcp[0]  # Thumb folded inwards
    else:
        return thumb_tip[0] > thumb_mcp[0]

def generate_frames():
    global alert_active, last_alert_time, last_screenshot_path, gesture_detected
    prev_gesture_detected = None  # Track previous gesture state
    while True:
        success, img = cap.read()
        if not success:
            logging.error("Failed to read from video capture")
            continue

        img = cv2.flip(img, 1)
        hands, img = detector.findHands(img, draw=True)

        detected = False
        if hands:
            hand = hands[0]
            if is_distress_signal(hand):
                detected = True
                if time.time() - last_alert_time > 5:
                    alert_active = True
                    last_alert_time = time.time()
                    if not pygame.mixer.get_busy():  # Play sound only if not already playing
                        alarm_sound.play()
                    gesture_detected = True
                    if prev_gesture_detected != detected:
                        time.sleep(10)  # Wait for 3 seconds before taking a screenshot
                        save_screenshot(img, correct=True)  # ✅ Save correct gesture
            else:
                if time.time() - last_alert_time > 5:
                    alert_active = False
                    gesture_detected = False
                    if prev_gesture_detected != detected:
                        save_screenshot(img, correct=False)  # ✅ Save incorrect gesture

        if alert_active:
            cvzone.putTextRect(img, "DISTRESS SIGNAL DETECTED!", [200, 100], 3, 4, (0, 0, 255), (255, 255, 255))
            cv2.rectangle(img, (50, 50), (1230, 670), (0, 0, 255), 10)

        # Convert to JPG and send frame
        ret, buffer = cv2.imencode('.jpg', img)
        if not ret:
            logging.error("Failed to encode image")
            continue

        frame = buffer.tobytes()
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def save_screenshot(img, correct):
    global last_screenshot_path
    os.makedirs(app.config['SCREENSHOT_FOLDER'], exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    label = "correct" if correct else "incorrect"
    filename = f"{label}_{timestamp}.jpg"
    screenshot_path = os.path.join(app.config['SCREENSHOT_FOLDER'], filename)

    # Save the image
    cv2.imwrite(screenshot_path, img)
    last_screenshot_path = f"/screenshots/{filename}"

    # Save details to database
    conn = sqlite3.connect("distress_signals.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO screenshots (filename, status, timestamp) VALUES (?, ?, ?)",
                   (filename, label, timestamp))
    conn.commit()
    conn.close()

@app.route('/check_gesture')
def check_gesture():
    global alert_active, last_screenshot_path, gesture_detected
    return jsonify({
        'gestureDetected': gesture_detected,
        'imagePath': last_screenshot_path
    })

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/check_alert')
def check_alert():
    global alert_active, last_screenshot_path, gesture_detected
    return jsonify({
        'alertActive': alert_active,
        'lastScreenshot': last_screenshot_path,
        'gestureDetected': gesture_detected
    })

@app.route('/screenshots/<filename>')
def serve_screenshot(filename):
    return send_from_directory(app.config['SCREENSHOT_FOLDER'], filename)

@app.route('/acknowledge_alert', methods=['POST'])
def acknowledge_alert():
    global alert_active
    alert_active = False
    alarm_sound.stop()
    return jsonify(success=True)

@app.route('/get_screenshots')
def get_screenshots():
    conn = sqlite3.connect("distress_signals.db")
    cursor = conn.cursor()
    cursor.execute("SELECT filename, status, timestamp FROM screenshots ORDER BY id DESC")
    screenshots = cursor.fetchall()
    conn.close()

    return jsonify([
        {"filename": row[0], "status": row[1], "timestamp": row[2], "imagePath": f"/screenshots/{row[0]}"}
        for row in screenshots
    ])

# Initialize Database
def init_db():
    conn = sqlite3.connect("distress_signals.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Call this once at the start
init_db()

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)
