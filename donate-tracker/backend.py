from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit
import requests
import time
import re
import logging
from datetime import datetime
from urllib.parse import unquote
from logging.handlers import RotatingFileHandler

# Настройка логирования с ротацией
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'donation_tracker.log',
            maxBytes=1024*1024,  # 1 MB
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'super_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Настройки API (ЗАМЕНИТЕ ТОКЕН!)
LZT_TOKEN = "ТОКЕН тут"
API_URL = "https://api.lzt.market/user/payments"

def log_event(event_type, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{event_type}] {message}"
    logging.info(log_message)

def get_donations():
    try:
        response = requests.get(
            API_URL,
            headers={"accept": "application/json", "authorization": LZT_TOKEN},
            params={"type": "receiving_money", "order": "desc", "limit": 50},
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("payments", {})
    except requests.exceptions.RequestException as e:
        log_event("API_ERROR", f"Ошибка запроса: {str(e)}")
    except ValueError:
        log_event("API_ERROR", "Некорректный JSON-ответ")
    return {}

def process_donation(donation):
    try:
        return {
            "username": donation["data"]["username"],
            "amount": f"{float(donation['incoming_sum']):.2f}",
            "comment": re.sub(r'<[^>]+>', '', unquote(donation["data"].get("comment", "")))
        }
    except (KeyError, ValueError) as e:
        log_event("DATA_ERROR", f"Ошибка обработки: {str(e)}")
        return None

def donation_worker():
    last_check = time.time()
    processed = set()
    
    while True:
        try:
            donations = get_donations()
            new_donations = []
            
            for d_id, donation in donations.items():
                if d_id in processed:
                    continue
                
                if not all(key in donation for key in ["data", "incoming_sum", "operation_date"]):
                    continue
                
                if donation["operation_date"] > last_check:
                    item = process_donation(donation)
                    if item:
                        new_donations.append(item)
                        processed.add(d_id)
                        log_event("NEW_DONATION", f"{item['username']} - {item['amount']} RUB")

            if new_donations:
                socketio.emit('new_donation', new_donations, room='donation_room')
                last_check = time.time()
            
            time.sleep(15)
            
        except Exception as e:
            log_event("WORKER_ERROR", f"Ошибка: {str(e)}")
            time.sleep(30)

@app.route('/')
def index():
    log_event("PAGE_VIEW", "Главная страница открыта")
    return render_template('index.html')

@app.route('/test')
def test():
    try:
        count = int(request.args.get('count', 1))
        if not 1 <= count <= 50:
            return "Допустимый диапазон: 1-50", 400
            
        test_data = [{
            "username": f"Тест #{i+1}",
            "amount": f"{(i+1)*100:.2f}",
            "comment": f"Тестовый донат №{i+1}"
        } for i in range(count)]
        
        socketio.emit('new_donation', test_data, room='donation_room')
        return f"Отправлено {count} тестовых донатов!"
        
    except ValueError:
        return "Неверный параметр count", 400

@socketio.on('join')
def handle_join(sid):
    join_room('donation_room')
    emit('status', {'message': 'Connected'})

if __name__ == '__main__':
    log_event("SYSTEM", "Сервер запущен")
    socketio.start_background_task(donation_worker)
    socketio.run(app, port=5000, debug=False)