# llmzima.py - Raspberry Pi client for hardware control

import sys # **** ADDED FOR DIAGNOSTICS ****
import os # Moved os import earlier for consistency
import logging # Moved logging import earlier

# **** START DIAGNOSTICS ****
print("--- SCRIPT START DIAGNOSTICS ---")
print(f"Python Executable: {sys.executable}")
print("sys.path:")
for p in sys.path:
    print(f"  - {p}")
# Check if a local 'telegram.py' or 'telegram' directory exists
current_script_directory = os.path.dirname(os.path.abspath(__file__))
local_telegram_py = os.path.join(current_script_directory, 'telegram.py')
local_telegram_dir = os.path.join(current_script_directory, 'telegram')
if os.path.exists(local_telegram_py):
    print(f"WARNING: Local file 'telegram.py' found at {local_telegram_py}. This might be shadowing the installed library.")
if os.path.exists(local_telegram_dir) and os.path.isdir(local_telegram_dir):
    print(f"WARNING: Local directory 'telegram/' found at {local_telegram_dir}. This might be shadowing the installed library.")
print("--- END DIAGNOSTICS ---")
# **** END DIAGNOSTICS ****

from flask import Flask, render_template, request, jsonify
import requests
import time
import json # Moved json import earlier
from datetime import datetime
import socket
import threading
import asyncio
from functools import wraps

# OpenWeatherMap API configuration
OPENWEATHER_API_KEY = ""  # Replace with your actual API key
OPENWEATHER_BASE_URL = "http://api.openweathermap.org/data/2.5/weather"
DEFAULT_CITY = "London"  # Default city for weather queries

# Function calling decorator
def function_call(func):
    """Decorator to mark functions as callable by the LLM"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper._is_function_call = True
    wrapper._function_name = func.__name__
    return wrapper

telegram = None # Initialize telegram to None
async_telegram = None 
telegram_errors = None # To store specific telegram error types if import is successful
# Replace lines 34-45 with this updated code:

try:
    import telegram
    from telegram import error as telegram_errors_module  # Use a different alias to avoid conflict
    # Get the correct error classes from the telegram library
    # The error was using 'Unauthorized' when it should be 'Forbidden'
    Unauthorized = telegram_errors_module.Forbidden  # Proper class name is Forbidden
    ChatNotFound = telegram_errors_module.BadRequest  # Use BadRequest for chat not found errors
    NetworkError = telegram_errors_module.NetworkError  # This one is correct
    logger_for_import = logging.getLogger(__name__)  # Get a logger instance for this block
    logger_for_import.info("Successfully imported 'python-telegram-bot' library and its error types.")
except ImportError as e:
    # This print goes to stdout, not the logger by default
    print("--------------------------------------------------------------------")
    print(f"CRITICAL-IMPORT-ERROR: The 'python-telegram-bot' library could not be imported.")
    print(f"Error details: {e}")
    print(f"Attempted to import from 'telegram'. Check if this module is shadowed or if the installation in {sys.executable} is corrupted.")
    print("Please ensure it's correctly installed in the active virtual environment: pip install python-telegram-bot")
    print("Telegram notifications will be disabled.")
    print("--------------------------------------------------------------------")
    # Also log it, so it appears in the file log if possible early on
    # Note: logger might not be fully configured here if this is the first thing that fails.
    # We will use the root logger for this specific early error.
    logging.getLogger().error(f"CRITICAL-IMPORT-ERROR: 'python-telegram-bot' library failed to import. Details: {e}. Telegram will be disabled.")
    # telegram remains None
    # Define dummy error classes so the rest of the script doesn't break if telegram was not imported
    class Unauthorized(Exception): pass
    class ChatNotFound(Exception): pass
    class NetworkError(Exception): pass

# Configure logging (if not already configured by the root logger above)
# This will append handlers if root logger was already touched by the import error log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("raspberry_client.log"),
        logging.StreamHandler()
    ],
    force=True # Force re-configuration or appending of handlers
)
logger = logging.getLogger(__name__)

# LLM Server configuration
LLM_SERVER_URL = "http://192.168.0.104:5000"  # always Replace with your Mac's IP address

# --- IMPORTANT TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = ""  # <<< --- !!! REPLACE THIS !!!
TELEGRAM_CHAT_ID = ""  # <<< --- !!! REPLACE THIS !!! e.g., "@yourchannel" or a numerical ID
TELEGRAM_ENABLED = True # Initial default, will be checked/updated based on import success
# --- END TELEGRAM CONFIGURATION ---

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')

# Check if running on Raspberry Pi or in development environment
RASPBERRY_PI = os.path.exists('/sys/class/gpio')

# GPIO pin configuration
SERVO_PIN1 = 12
SERVO_PIN2 = 23
TRIG_PIN = 21
ECHO_PIN = 20

@function_call
def get_weather_data(city=None, units="metric"):
    """
    Fetch current weather data from OpenWeatherMap API
    
    Args:
        city (str): City name (defaults to DEFAULT_CITY)
        units (str): Temperature units - 'metric', 'imperial', or 'kelvin'
    
    Returns:
        dict: Weather data or error information
    """
    if not city:
        city = DEFAULT_CITY
    
    if not OPENWEATHER_API_KEY or OPENWEATHER_API_KEY == "YOUR_OPENWEATHER_API_KEY":
        logger.error("OpenWeatherMap API key not configured")
        return {
            "success": False,
            "error": "Weather API key not configured",
            "message": "Please set OPENWEATHER_API_KEY in the configuration"
        }
    
    try:
        params = {
            "q": city,
            "appid": OPENWEATHER_API_KEY,
            "units": units
        }
        
        logger.info(f"Fetching weather data for {city}")
        response = requests.get(OPENWEATHER_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        weather_data = response.json()
        
        # Format the response
        formatted_data = {
            "success": True,
            "city": weather_data["name"],
            "country": weather_data["sys"]["country"],
            "temperature": weather_data["main"]["temp"],
            "feels_like": weather_data["main"]["feels_like"],
            "humidity": weather_data["main"]["humidity"],
            "pressure": weather_data["main"]["pressure"],
            "description": weather_data["weather"][0]["description"],
            "wind_speed": weather_data.get("wind", {}).get("speed", 0),
            "units": units,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Weather data retrieved successfully for {city}")
        return formatted_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weather data: {e}")
        return {
            "success": False,
            "error": "Network error",
            "message": f"Failed to fetch weather data: {str(e)}"
        }
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing weather data: {e}")
        return {
            "success": False,
            "error": "Data parsing error",
            "message": "Invalid response from weather service"
        }
    except Exception as e:
        logger.error(f"Unexpected error fetching weather: {e}")
        return {
            "success": False,
            "error": "Unexpected error",
            "message": str(e)
        }

class HardwareController:
    def __init__(self):
        # Add servo position tracking
        self.servo1_position = 0  # Current angle in degrees
        self.servo2_position = 0  # Current angle in degrees
        
        if RASPBERRY_PI:
            try:
                import RPi.GPIO as GPIO
                self.GPIO = GPIO
                self.GPIO.setmode(GPIO.BCM)
                self.GPIO.setwarnings(False)

                self.GPIO.setup(SERVO_PIN1, GPIO.OUT)
                self.GPIO.setup(SERVO_PIN2, GPIO.OUT)
                self.GPIO.setup(TRIG_PIN, GPIO.OUT)
                self.GPIO.setup(ECHO_PIN, GPIO.IN)

                self.servo1 = GPIO.PWM(SERVO_PIN1, 50)
                self.servo2 = GPIO.PWM(SERVO_PIN2, 50)
                self.servo1.start(0)
                self.servo2.start(0)
                
                self.mock_mode = False
                logger.info("Hardware controller initialized in HARDWARE mode")
            except Exception as e:
                logger.error(f"Error initializing GPIO: {e}")
                self.mock_mode = True
                logger.warning("Falling back to MOCK mode due to error")
        else:
            self.mock_mode = True
            logger.warning("Hardware controller initialized in MOCK mode (not running on Raspberry Pi)")

    def dispense_pill(self, servo_num):
        if self.mock_mode:
            logger.info(f"MOCK: Dispensing pill from servo {servo_num}")
            return
            
        if servo_num == 1:
            logger.info(f"Dispensing pill from servo 1 (Paracetamol)")
            self._rotate_servo(self.servo1)
        elif servo_num == 2:
            logger.info(f"Dispensing pill from servo 2 (Antibiotic)")
            self._rotate_servo(self.servo2)

    def _rotate_servo(self, servo):
        if self.mock_mode:
            return
            
        servo.ChangeDutyCycle(7.5)
        time.sleep(0.5)
        servo.ChangeDutyCycle(2.5)
        time.sleep(0.5)
        servo.ChangeDutyCycle(0)

    @function_call
    def rotate_servo_90_degrees(self, servo_num, direction="clockwise"):
        """
        Rotate servo motor by 90 degrees
        
        Args:
            servo_num (int): Servo number (1 or 2)
            direction (str): 'clockwise' or 'counterclockwise'
        
        Returns:
            dict: Operation result
        """
        if servo_num not in [1, 2]:
            logger.error(f"Invalid servo number: {servo_num}")
            return {
                "success": False,
                "error": "Invalid servo number",
                "message": "Servo number must be 1 or 2"
            }
        
        if self.mock_mode:
            current_pos = self.servo1_position if servo_num == 1 else self.servo2_position
            rotation_amount = 90 if direction == "clockwise" else -90
            new_position = (current_pos + rotation_amount) % 360
            
            if servo_num == 1:
                self.servo1_position = new_position
            else:
                self.servo2_position = new_position
                
            logger.info(f"MOCK: Servo {servo_num} rotated 90° {direction}. New position: {new_position}°")
            return {
                "success": True,
                "servo": servo_num,
                "direction": direction,
                "new_position": new_position,
                "message": f"Servo {servo_num} rotated 90° {direction} to {new_position}°"
            }
        
        try:
            servo = self.servo1 if servo_num == 1 else self.servo2
            current_pos = self.servo1_position if servo_num == 1 else self.servo2_position
            
            # Calculate new position
            rotation_amount = 90 if direction == "clockwise" else -90
            new_position = (current_pos + rotation_amount) % 360
            
            # Convert angle to duty cycle (0-180 degrees mapped to 2.5-12.5% duty cycle)
            duty_cycle = 2.5 + (new_position / 180.0) * 10.0
            
            # Rotate servo
            servo.ChangeDutyCycle(duty_cycle)
            time.sleep(0.5)  # Allow time for rotation
            servo.ChangeDutyCycle(0)  # Stop sending signal
            
            # Update position tracking
            if servo_num == 1:
                self.servo1_position = new_position
            else:
                self.servo2_position = new_position
            
            logger.info(f"Servo {servo_num} rotated 90° {direction}. New position: {new_position}°")
            return {
                "success": True,
                "servo": servo_num,
                "direction": direction,
                "new_position": new_position,
                "message": f"Servo {servo_num} rotated 90° {direction} to {new_position}°"
            }
            
        except Exception as e:
            logger.error(f"Error rotating servo {servo_num}: {e}")
            return {
                "success": False,
                "error": "Hardware error",
                "message": f"Failed to rotate servo {servo_num}: {str(e)}"
            }
    
    def get_servo_position(self, servo_num):
        """Get current servo position"""
        if servo_num == 1:
            return self.servo1_position
        elif servo_num == 2:
            return self.servo2_position
        else:
            return None

    def measure_distance(self):
        if self.mock_mode:
            import random
            distance = round(random.uniform(5, 20), 2)
            logger.debug(f"MOCK: Measured distance: {distance} cm")
            return distance
        
        if not RASPBERRY_PI or not hasattr(self, 'GPIO') or not self.GPIO:
            logger.warning("Attempted to measure distance in mock mode or without GPIO initialized.")
            return 999 # Return an error/default distance

        try:
            self.GPIO.output(TRIG_PIN, False)
            time.sleep(0.5) 
            self.GPIO.output(TRIG_PIN, True)
            time.sleep(0.00001) 
            self.GPIO.output(TRIG_PIN, False)

            pulse_start_time = time.time()
            measurement_timeout = time.time() + 0.1

            while self.GPIO.input(ECHO_PIN) == 0:
                pulse_start_time = time.time()
                if pulse_start_time > measurement_timeout:
                    logger.warning("Distance measurement timeout (waiting for echo start)")
                    return 999
                    
            pulse_end_time = time.time() 
            while self.GPIO.input(ECHO_PIN) == 1:
                pulse_end_time = time.time()
                if pulse_end_time > measurement_timeout: 
                    logger.warning("Distance measurement timeout (waiting for echo end)")
                    return 999

            pulse_duration = pulse_end_time - pulse_start_time
            distance = pulse_duration * 17150 
            distance = round(distance, 2)
            logger.debug(f"Measured distance: {distance} cm")
            return distance
        except Exception as e:
            logger.error(f"Error during distance measurement: {e}", exc_info=True)
            return 999 # Error value

    def cleanup(self):
        if self.mock_mode:
            return
        if RASPBERRY_PI and hasattr(self, 'GPIO') and self.GPIO: 
            try:
                if hasattr(self, 'servo1') and self.servo1: self.servo1.stop()
                if hasattr(self, 'servo2') and self.servo2: self.servo2.stop()
                self.GPIO.cleanup()
                logger.info("GPIO resources cleaned up")
            except Exception as e:
                logger.error(f"Error during GPIO cleanup: {e}")

# Get local IP address
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1) 
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        logger.error(f"Error getting local IP: {e}")
        return "127.0.0.1" 

def test_telegram_connection():
    """Test the telegram connection and report detailed results"""
    if not TELEGRAM_ENABLED:
        logger.warning("Telegram is disabled. Cannot test connection.")
        return False
    
    if not telegram:
        logger.error("Telegram library not imported successfully. Cannot test connection.")
        return False
    
    try:
        logger.info(f"Testing Telegram connection with token ending in '...{TELEGRAM_BOT_TOKEN[-6:]}'")
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        bot_info = bot.get_me()
        logger.info(f"Telegram connection successful! Connected to bot: {bot_info.first_name} (@{bot_info.username})")
        
        # Try sending a test message
        test_message = f"Test message from zimaPharma ({datetime.now().strftime('%H:%M:%S')})"
        logger.info(f"Attempting to send test message to chat_id: {TELEGRAM_CHAT_ID}")
        message = bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=test_message)
        logger.info(f"Test message sent successfully to {TELEGRAM_CHAT_ID}! Message ID: {message.message_id}")
        return True
    except Exception as e:
        logger.error(f"Telegram test connection failed: {e.__class__.__name__}: {e}", exc_info=True)
        
        # Provide helpful troubleshooting tips
        if "Forbidden" in str(e) or "Unauthorized" in str(e):
            logger.error("This usually means your bot token is invalid. Check it at BotFather.")
        elif "chat not found" in str(e).lower() or "Chat_id" in str(e):
            logger.error(f"Chat '{TELEGRAM_CHAT_ID}' not found. Make sure:")
            logger.error("1. For private chats: The user has started a conversation with the bot")
            logger.error("2. For groups: The bot has been added to the group")
            logger.error("3. For channels: The bot is an admin in the channel")
        
        return False

# Global connection status
connection_status = {"connected": False}

# Utility functions for communicating with the LLM server
def call_api(endpoint, method="GET", data=None):
    url = f"{LLM_SERVER_URL}{endpoint}"
    try:
        logger.debug(f"Calling API: {method} {url}")
        timeout = 250 if "chat" in endpoint else 10 
        
        if method == "GET":
            response = requests.get(url, timeout=timeout)
        else:
            response = requests.post(url, json=data, timeout=timeout)
        
        response.raise_for_status() 
        logger.debug(f"API call successful: {url}")
        if 'application/json' in response.headers.get('Content-Type', ''):
            return response.json()
        else:
            logger.warning(f"API response from {url} is not JSON. Response text: {response.text[:100]}")
            return {"success": False, "error": "Non-JSON response from server", "data": response.text}
    except requests.exceptions.HTTPError as e:
        logger.error(f"API call HTTP error: {url}, Status: {e.response.status_code}, Response: {e.response.text[:200]}") 
        return {"success": False, "error": f"API call failed with status {e.response.status_code}"}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to server {LLM_SERVER_URL}: {e}")
        return {"success": False, "error": f"Cannot connect to LLM server: {e}"}
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout connecting to server {LLM_SERVER_URL}: {e}")
        return {"success": False, "error": f"Timeout connecting to LLM server: {e}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"API call to {endpoint} failed: {e}")
        return {"success": False, "error": f"API call failed: {e}"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from {url}: {e}. Response text (first 200 chars): {response.text[:200] if 'response' in locals() else 'Response object not available'}")
        return {"success": False, "error": "Invalid JSON response from server"}

def check_server_connection():
    api_response = call_api("/api/heartbeat") 
    if api_response and api_response.get("status") == "ok":
        return True
    return False
    
# Register with the server on startup
def register_with_server():
    data = {
        "client_type": "raspberry_pi",
        "client_ip": local_ip,
        "client_version": "1.0",
        "hardware_mode": "real" if not hardware.mock_mode else "mock"
    }
    api_response = call_api("/api/register_client", method="POST", data=data)
    if api_response and api_response.get("success", True) != False : 
        logger.info(f"Successfully registered with server at {LLM_SERVER_URL}")
        return True
    else:
        logger.warning(f"Server registration failed. Response: {api_response}")
        return False

# Local response generation when server is unavailable
def generate_local_response(user_input):
    user_input_lower = user_input.lower()
    
    # Weather queries
    if any(word in user_input_lower for word in ["weather", "temperature", "forecast", "rain", "sunny", "cloudy"]):
        # Extract city if mentioned
        city = DEFAULT_CITY
        for word in user_input.split():
            if word.lower() not in ["weather", "in", "the", "what's", "how's"]:
                city = word
                break
        
        weather_data = get_weather_data(city)
        if weather_data.get('success'):
            temp_unit = "°C" if weather_data.get('units') == 'metric' else "°F"
            return f"The weather in {weather_data['city']} is {weather_data['temperature']}{temp_unit} with {weather_data['description']}. Humidity: {weather_data['humidity']}%"
        else:
            return f"Sorry, I couldn't get weather information: {weather_data.get('message', 'Unknown error')}"
    
    # Servo rotation commands
    if any(word in user_input_lower for word in ["rotate", "turn", "servo", "motor"]):
        servo_num = 1
        direction = "clockwise"
        
        if "2" in user_input_lower or "two" in user_input_lower:
            servo_num = 2
        if "counter" in user_input_lower or "anti" in user_input_lower or "left" in user_input_lower:
            direction = "counterclockwise"
            
        result = hardware.rotate_servo_90_degrees(servo_num, direction)
        if result.get('success'):
            return f"Servo {servo_num} rotated 90° {direction}. New position: {result['new_position']}°"
        else:
            return f"Failed to rotate servo: {result.get('message', 'Unknown error')}"
    
    # Existing medication responses
    if any(word in user_input_lower for word in ["headache", "pain", "hurt", "head", "ache"]):
        return "For headaches, I recommend taking Paracetamol from slot 1. Would you like me to dispense it for you?"
    elif any(word in user_input_lower for word in ["fever", "temperature", "hot", "cold"]):
        return "If you have a fever, Paracetamol from slot 1 can help reduce it. Would you like me to dispense it?"
    elif any(word in user_input_lower for word in ["infection", "antibiotic", "bacteria"]):
        return "The Antibiotic in slot 2 is for bacterial infections and should be taken with food. Would you like me to dispense it?"
    elif any(word in user_input_lower for word in ["dispense", "give", "take"]):
        if "paracetamol" in user_input_lower or "slot 1" in user_input_lower or "1" in user_input_lower:
            return "Dispensing Paracetamol from slot 1. Please take it with water."
        elif "antibiotic" in user_input_lower or "slot 2" in user_input_lower or "2" in user_input_lower:
            return "Dispensing Antibiotic from slot 2. Remember to take it with food."
    elif any(word in user_input_lower for word in ["help", "emergency"]):
        return "If this is a medical emergency, please contact emergency services immediately."
    
    return "I'm currently operating in offline mode with limited capabilities. I can help you dispense medication, check pill pickup, get weather information, or control servo motors."

# Chat history - local cache
chat_history = []

# Instantiate hardware controller
hardware = HardwareController()
local_ip = get_local_ip()

# Periodic connection check
def periodic_connection_check():
    while True:
        try:
            connected = check_server_connection()
            if connected != connection_status["connected"]:
                connection_status["connected"] = connected
                status_msg = "Online" if connected else "Offline"
                logger.info(f"Server connection status changed to: {status_msg}")
                
                chat_history.append({
                    'type': 'system',
                    'sender': 'System',
                    'message': f'LLM server connection {"restored" if connected else "lost"}. Operating in {"online" if connected else "offline"} mode.',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                if connected: 
                    register_with_server()
        except Exception as e:
            logger.error(f"Error in periodic connection check: {e}", exc_info=True)
        time.sleep(30) 

async def send_telegram_notification_async(message, priority="normal"):
    """Asynchronously send notification to caregiver via Telegram"""
    global TELEGRAM_ENABLED 

    if not TELEGRAM_ENABLED:
        logger.info(f"Telegram notifications globally disabled. Would have sent: {message}")
        return False

    if not telegram: 
        logger.error("Telegram library object is None (import likely failed). Cannot send notification.")
        return False

    if TELEGRAM_BOT_TOKEN == "YOUR_ACTUAL_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram Bot Token is not configured. Please set it at the top of the script.")
        return False
    
    if TELEGRAM_CHAT_ID == "YOUR_ACTUAL_CHAT_ID" or not TELEGRAM_CHAT_ID:
        logger.error("Telegram Chat ID is not configured. Please set it at the top of the script.")
        return False
        
    try:
        logger.info(f"Attempting to send Telegram notification to chat ID '{TELEGRAM_CHAT_ID}' with token ending in '...{TELEGRAM_BOT_TOKEN[-6:]}'.")
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        
        if priority == "emergency":
            formatted_message = f"🚨 EMERGENCY ALERT: {message}"
        elif priority == "warning":
            formatted_message = f"⚠️ WARNING: {message}"
        else:
            formatted_message = f"ℹ️ {message}"
            
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=formatted_message)
        logger.info(f"Telegram notification sent successfully: {message}")
        return True
    except telegram_errors_module.Forbidden:
        logger.error(f"Telegram Forbidden: Bot token '{TELEGRAM_BOT_TOKEN[:10]}...' might be invalid.")
        return False
    except telegram_errors_module.BadRequest as e:
        if "chat not found" in str(e).lower():
            logger.error(f"Telegram Chat Not Found: The chat_id '{TELEGRAM_CHAT_ID}' was not found. Ensure it's correct.")
        else:
            logger.error(f"Telegram BadRequest: {e}")
        return False
    except telegram_errors_module.NetworkError as e:
        logger.error(f"Telegram NetworkError: Failed to connect to Telegram servers. Check internet connection. Details: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram notification due to an unexpected error: {e.__class__.__name__} - {e}", exc_info=True)
        return False

def run_send_telegram_notification(message, priority="normal"):
    """Helper function to run the async notification sender from sync code"""
    if not TELEGRAM_ENABLED:
        logger.debug(f"run_send_telegram_notification: TELEGRAM_ENABLED is False. Skipping for: {message}")
        return False
    try:
        return asyncio.run(send_telegram_notification_async(message, priority))
    except RuntimeError as e:
        if "cannot be called when another asyncio event loop is running" in str(e) or \
           "Nesting asyncio.run() is not supported" in str(e): 
            logger.error(f"asyncio.run() error: {e}. This can happen in threaded environments with existing loops.")
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
                if loop.is_running():
                    logger.info("Event loop is running, creating a task for telegram notification.")
                    asyncio.run_coroutine_threadsafe(send_telegram_notification_async(message, priority), loop)
                    return True 
                else:
                    logger.info("Event loop exists but not running, using new_event_loop and run_until_complete (fallback).")
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(send_telegram_notification_async(message, priority))
                    finally:
                        new_loop.close()
                        asyncio.set_event_loop(None)
                    return result
            except Exception as inner_e:
                logger.error(f"Fallback asyncio handling also failed: {inner_e}", exc_info=True)
                return False
        else:
            logger.error(f"RuntimeError calling send_telegram_notification_async: {e}", exc_info=True)
            return False
    except Exception as e: 
        logger.error(f"Unexpected error in run_send_telegram_notification: {e}", exc_info=True)
        return False

def check_missed_medications():
    while True:
        try:
            now = datetime.now()
            medications = []
            if connection_status["connected"]:
                api_response = call_api("/api/get_schedule")
                if api_response and api_response.get("success", True) and isinstance(api_response.get("today"), list):
                    medications = api_response.get("today", [])
                else:
                    logger.warning(f"Failed to get schedule or invalid format from server for missed medication check. Response: {api_response}")
            else:
                next_hour = (now.hour + 1) % 24
                medications = [
                    {"name": "Antibiotic", "dosage": "250mg", "time": "08:00", "slot": 2, "status": "taken"},
                    {"name": "Paracetamol", "dosage": "500mg", "time": f"{next_hour:02d}:00", "slot": 1, "status": "upcoming"}
                ]
            
            if not medications:
                logger.debug("No medications in schedule to check for missed doses.")
            
            for med in medications:
                med_time_str = med.get("time")
                med_status = med.get("status")
                med_name = med.get("name")
                
                if med_time_str and med_status == "upcoming":
                    try:
                        med_datetime = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {med_time_str}", "%Y-%m-%d %H:%M")
                        if now > med_datetime and (now - med_datetime).total_seconds() > 1800: 
                            logger.warning(f"Missed medication detected: {med_name} at {med_time_str}. Sending notification.")
                            run_send_telegram_notification(
                                f"MISSED MEDICATION: {med_name} scheduled for {med_time_str} hasn't been taken.",
                                priority="warning"
                            )
                    except ValueError:
                        logger.error(f"Invalid time format for medication '{med_name}': '{med_time_str}'")
            time.sleep(15 * 60)
        except Exception as e:
            logger.error(f"Error in medication reminder check: {e}", exc_info=True)
            time.sleep(60)

# Flask routes
@app.route('/')
def index():
    try:
        users_data = {"users": []}
        if connection_status["connected"]:
            server_response = call_api("/api/users")
            if server_response and server_response.get("success", True) and isinstance(server_response.get("users"), list):
                users_data = {"users": server_response.get("users", [])}
            else:
                logger.warning(f"Failed to get user data or invalid format from server for index page. Response: {server_response}")
        else:
            users_data = {"users": [
                {"id": "1", "personal": {"name": "Default User", "age": 40, "gender": "Unknown"},
                 "medications": [
                     {"name": "Paracetamol", "dosage": "500mg", "schedule": "As needed", "slot": 1},
                     {"name": "Antibiotic", "dosage": "250mg", "schedule": "Every 8 hours", "slot": 2}]}
            ]}
        current_user_id = "1"
        user = next((u for u in users_data.get('users', []) if u.get('id') == current_user_id), {})
        user_options = [{'id': u.get('id'), 'name': u.get('personal', {}).get('name', 'Unknown')} 
                        for u in users_data.get('users', [])]
        return render_template('index.html', chat_history=chat_history, user_data=user,
                               current_user=current_user_id, user_options=user_options,
                               server_connected=connection_status["connected"], server_url=LLM_SERVER_URL)
    except Exception as e:
        logger.error(f"Error rendering index page: {e}", exc_info=True)
        return render_template('error.html', error=str(e))

@app.route('/error')
def error_page():
    error = request.args.get('message', 'Unknown error')
    return render_template('error.html', error=error)

@app.route('/dispense/<int:compartment>', methods=['POST'])
def dispense(compartment):
    if compartment in [1, 2]:
        hardware.dispense_pill(compartment)
        med_name = "Paracetamol" if compartment == 1 else "Antibiotic"
        chat_history.append({
            'type': 'system', 'sender': 'System',
            'message': f'{med_name} dispensed from compartment {compartment}',
            'timestamp': datetime.now().strftime('%H:%M:%S')})
        logger.info(f"Dispensed {med_name} from compartment {compartment}")
        return jsonify({'status': f'{med_name} dispensed from compartment {compartment}'})
    logger.warning(f"Invalid compartment number: {compartment}")
    return jsonify({'error': 'Invalid compartment number'}), 400

@app.route('/distance', methods=['GET'])
def get_distance():
    distance = hardware.measure_distance()
    return jsonify({'distance_cm': distance})

@app.route('/check_pill_pickup', methods=['GET'])
def check_pill_pickup():
    distance = hardware.measure_distance()
    threshold = 10
    pill_taken = distance < threshold
    status = 'Pill taken' if pill_taken else 'Pill not taken'
    
    if pill_taken:
        chat_history.append({'type': 'system', 'sender': 'System', 'message': 'Pill pickup detected', 'timestamp': datetime.now().strftime('%H:%M:%S')})
        logger.info(f"Pill pickup detected. Distance: {distance} cm")
    else:
        med_info = request.args.get('medication', 'Medication')
        time_info = request.args.get('time', datetime.now().strftime('%H:%M'))
        logger.warning(f"No pill pickup detected for {med_info} at {time_info}. Distance: {distance} cm. Sending notification.")
        run_send_telegram_notification(
            f"Patient hasn't picked up {med_info} scheduled for {time_info}. Distance: {distance} cm.",
            priority="warning"
        )
        chat_history.append({'type': 'system', 'sender': 'System', 
                             'message': f'Pill ({med_info}) not picked up. Caregiver notified. Distance: {distance} cm.',
                             'timestamp': datetime.now().strftime('%H:%M:%S')})
    return jsonify({'status': status, 'distance_cm': distance, 'pill_taken': pill_taken})

@app.route('/weather', methods=['GET'])
def get_weather():
    """Get weather data for a specified city"""
    city = request.args.get('city', DEFAULT_CITY)
    units = request.args.get('units', 'metric')
    
    weather_data = get_weather_data(city, units)
    
    if weather_data.get('success'):
        chat_history.append({
            'type': 'system',
            'sender': 'Weather',
            'message': f"Weather in {weather_data['city']}: {weather_data['temperature']}°{'C' if units=='metric' else 'F'}, {weather_data['description']}",
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
        logger.info(f"Weather data retrieved for {city}")
    else:
        chat_history.append({
            'type': 'error',
            'sender': 'Weather',
            'message': f"Failed to get weather for {city}: {weather_data.get('message', 'Unknown error')}",
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
    
    return jsonify(weather_data)

@app.route('/servo_rotate', methods=['POST'])
def rotate_servo():
    """Rotate servo motor by 90 degrees"""
    data = request.json
    servo_num = data.get('servo_num', 1)
    direction = data.get('direction', 'clockwise')
    
    if direction not in ['clockwise', 'counterclockwise']:
        return jsonify({
            'success': False,
            'error': 'Invalid direction',
            'message': 'Direction must be "clockwise" or "counterclockwise"'
        }), 400
    
    result = hardware.rotate_servo_90_degrees(servo_num, direction)
    
    if result.get('success'):
        chat_history.append({
            'type': 'system',
            'sender': 'Hardware',
            'message': f"Servo {servo_num} rotated 90° {direction}",
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
        logger.info(f"Servo {servo_num} rotated 90° {direction} via manual control")
    else:
        chat_history.append({
            'type': 'error',
            'sender': 'Hardware',
            'message': f"Failed to rotate servo {servo_num}: {result.get('message', 'Unknown error')}",
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
    
    return jsonify(result)

@app.route('/servo_position/<int:servo_num>', methods=['GET'])
def get_servo_position_route(servo_num):
    """Get current servo position"""
    position = hardware.get_servo_position(servo_num)
    
    if position is not None:
        return jsonify({
            'success': True,
            'servo': servo_num,
            'position': position,
            'message': f'Servo {servo_num} position: {position}°'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Invalid servo number',
            'message': 'Servo number must be 1 or 2'
        }), 400

@app.route('/function_call', methods=['POST'])
def handle_function_call():
    """Handle function calls from the LLM or UI"""
    data = request.json
    function_name = data.get('function_name')
    function_args = data.get('args', {})
    
    # Available functions
    available_functions = {
        'get_weather_data': get_weather_data,
        'rotate_servo_90_degrees': hardware.rotate_servo_90_degrees
    }
    
    if function_name not in available_functions:
        return jsonify({
            'success': False,
            'error': 'Function not found',
            'message': f'Function "{function_name}" is not available'
        }), 400
    
    try:
        result = available_functions[function_name](**function_args)
        logger.info(f"Function call executed: {function_name} with args: {function_args}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error executing function {function_name}: {e}")
        return jsonify({
            'success': False,
            'error': 'Function execution error',
            'message': str(e)
        }), 500

@app.route('/llm_response', methods=['POST'])
def llm_response():
    user_input = request.json.get('message', '')
    chat_history.append({'type': 'user', 'sender': 'You', 'message': user_input, 'timestamp': datetime.now().strftime('%H:%M:%S')})
    logger.info(f"User message: {user_input}")
    
    response_text = ""
    if not connection_status["connected"]:
        logger.warning("Server not connected, using local fallback response")
        response_text = generate_local_response(user_input)
    else:
        api_response = call_api("/api/chat", method="POST", data={"message": user_input})
        if api_response and api_response.get("success", True) and isinstance(api_response.get("response"), str) :
            response_text = api_response.get("response")
        else:
            err_msg = api_response.get('error', 'Unknown error') if api_response else "No response from API"
            logger.warning(f"Failed to get LLM response or invalid format: {err_msg}. Response: {api_response}")
            response_text = generate_local_response(user_input)
    
    chat_history.append({'type': 'bot', 'sender': 'Assistant', 'message': response_text, 'timestamp': datetime.now().strftime('%H:%M:%S')})
    return jsonify({'response': response_text})

@app.route('/voice_command', methods=['POST'])
def voice_command():
    command = request.json.get("command", "")
    logger.info(f"Received voice command: {command}")
    chat_history.append({'type': 'user', 'sender': 'Voice', 'message': command, 'timestamp': datetime.now().strftime('%H:%M:%S')})
    
    response_text = ""
    command_lower = command.lower()

    # Weather commands
    if any(word in command_lower for word in ["weather", "temperature", "forecast"]):
        city = DEFAULT_CITY
        for word in command.split():
            if word.lower() not in ["weather", "in", "the", "what's", "how's"]:
                city = word
                break
        
        weather_data = get_weather_data(city)
        if weather_data.get('success'):
            temp_unit = "°C" if weather_data.get('units') == 'metric' else "°F"
            response_text = f"The weather in {weather_data['city']} is {weather_data['temperature']}{temp_unit} with {weather_data['description']}"
        else:
            response_text = f"Sorry, I couldn't get weather information: {weather_data.get('message', 'Unknown error')}"
    
    # Servo rotation commands
    elif any(word in command_lower for word in ["rotate", "turn", "servo", "motor"]):
        servo_num = 1
        direction = "clockwise"
        
        if "2" in command_lower or "two" in command_lower:
            servo_num = 2
        if "counter" in command_lower or "anti" in command_lower or "left" in command_lower:
            direction = "counterclockwise"
            
        result = hardware.rotate_servo_90_degrees(servo_num, direction)
        if result.get('success'):
            response_text = f"Servo {servo_num} rotated 90 degrees {direction}"
        else:
            response_text = f"Failed to rotate servo: {result.get('message', 'Unknown error')}"
    
    elif "dispense" in command_lower and ("paracetamol" in command_lower or "slot 1" in command_lower or "one" in command_lower):
        hardware.dispense_pill(1)
        response_text = "Dispensing Paracetamol from compartment 1."
    elif "dispense" in command_lower and ("antibiotic" in command_lower or "slot 2" in command_lower or "two" in command_lower):
        hardware.dispense_pill(2)
        response_text = "Dispensing Antibiotic from compartment 2."
    elif "distance" in command_lower or "measure" in command_lower or "pickup" in command_lower or "check pill" in command_lower:
        distance = hardware.measure_distance()
        response_text = f"Pill pickup {'detected' if distance < 10 else 'not detected'}. Distance is {distance} cm."
    elif "emergency" in command_lower or "help" in command_lower:
        chat_history.append({'type': 'error', 'sender': 'System', 'message': 'EMERGENCY ALERT TRIGGERED VIA VOICE', 'timestamp': datetime.now().strftime('%H:%M:%S')})
        run_send_telegram_notification("EMERGENCY ALERT triggered by voice command from patient.", priority="emergency")
        response_text = "Emergency alert triggered. Help has been notified."
        logger.critical("EMERGENCY ALERT triggered by voice command.")
    else:
        if connection_status["connected"]:
            api_response = call_api("/api/chat", method="POST", data={"message": command})
            if api_response and api_response.get("success", True) and isinstance(api_response.get("response"), str):
                response_text = api_response.get("response")
            else:
                logger.warning(f"LLM response for voice command failed or invalid format. Response: {api_response}")
                response_text = generate_local_response(command)
        else:
            response_text = generate_local_response(command)
    
    chat_history.append({'type': 'bot', 'sender': 'Bot', 'message': response_text, 'timestamp': datetime.now().strftime('%H:%M:%S')})
    logger.info(f"Voice command response: {response_text}")
    return jsonify({"message": response_text})

@app.route('/emergency', methods=['POST'])
def emergency():
    chat_history.append({'type': 'error', 'sender': 'System', 'message': 'EMERGENCY ALERT TRIGGERED FROM UI', 'timestamp': datetime.now().strftime('%H:%M:%S')})
    run_send_telegram_notification("EMERGENCY ALERT triggered from the web interface.", priority="emergency")
    logger.critical("EMERGENCY ALERT TRIGGERED FROM UI")
    return jsonify({"status": "Emergency alert triggered and caregiver notified."})

@app.route('/select_user', methods=['POST'])
def select_user_route(): 
    user_id = request.json.get('user_id', '')
    logger.info(f"Selecting user: {user_id}")
    if connection_status["connected"]:
        api_response = call_api("/api/select_user", method="POST", data={"user_id": user_id})
        if api_response and api_response.get("success", True) and isinstance(api_response.get("user"), dict):
            return jsonify({"status": "success", "user": api_response.get("user")})
        else:
            err_msg = api_response.get('error', 'Unknown error') if api_response else "No response from API"
            logger.warning(f"Failed to select user {user_id} or invalid format: {err_msg}. Response: {api_response}")
            return jsonify({"status": "error", "message": "User not found or server error"}), 404
    else:
        logger.warning("Server offline, cannot select user via server.")
        return jsonify({"status": "error", "message": "Server offline, cannot select user"}), 503

@app.route('/add_user', methods=['POST'])
def add_user_route(): 
    try:
        new_user_data = request.json
        user_name = new_user_data.get('personal', {}).get('name', 'Unknown')
        logger.info(f"Attempting to add new user: {user_name}")
        if not connection_status["connected"]:
            logger.warning("Server offline, cannot add user via server.")
            return jsonify({"status": "error", "message": "Server offline, cannot add user"}), 503
        
        api_response = call_api("/api/add_user", method="POST", data=new_user_data)
        if not (api_response and api_response.get("success", True) and api_response.get("user_id")):
            err_msg = api_response.get('error', 'Unknown error') if api_response else "No response or missing user_id from API"
            logger.warning(f"Failed to add user: {err_msg}. Response: {api_response}")
            return jsonify({"status": "error", "message": err_msg}), 500
        
        chat_history.append({'type': 'system', 'sender': 'System', 'message': f'New user created: {user_name}', 'timestamp': datetime.now().strftime('%H:%M:%S')})
        logger.info(f"User added successfully: ID {api_response.get('user_id')}")
        return jsonify({"status": "success", "user_id": api_response.get("user_id")})
    except Exception as e:
        logger.error(f"Error adding user: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_medication_info/<int:slot>', methods=['GET'])
def get_medication_info_route(slot): 
    if not connection_status["connected"]:
        if slot == 1: return jsonify({"name": "Paracetamol", "dosage": "500mg", "schedule": "As needed", "description": "Use for pain or fever...", "icon": "bi-capsule"})
        if slot == 2: return jsonify({"name": "Antibiotic", "dosage": "250mg", "schedule": "Every 8 hours", "description": "Take with food...", "icon": "bi-pill"})
        return jsonify({"error": "Invalid slot number"}), 400
    
    api_response = call_api(f"/api/get_medication_info/{slot}")
    if api_response and api_response.get("success", True) and api_response.get("name"): 
        return jsonify(api_response) 
    else:
        err_msg = api_response.get('error', 'Unknown error') if api_response else f"No response or missing name for slot {slot}"
        logger.warning(f"Failed to get medication info for slot {slot} from server: {err_msg}. Falling back. Response: {api_response}")
        if slot == 1: return jsonify({"name": "Paracetamol (Srv Err)", "dosage": "500mg", "description": "Err fetch.", "icon": "bi-capsule"})
        if slot == 2: return jsonify({"name": "Antibiotic (Srv Err)", "dosage": "250mg", "description": "Err fetch.", "icon": "bi-pill"})
        return jsonify({"error": f"Invalid slot or server error: {err_msg}"}), 400

@app.route('/get_schedule', methods=['GET'])
def get_schedule_route(): 
    if connection_status["connected"]:
        api_response = call_api("/api/get_schedule")
        if api_response and api_response.get("success", True) and isinstance(api_response.get("today"), list) and isinstance(api_response.get("upcoming"), dict):
            return jsonify(api_response)
        else:
            logger.warning(f"Failed to get schedule from server or invalid format. Response: {api_response}")
    
    now = datetime.now()
    next_hour = (now.hour + 1) % 24
    return jsonify({
        "upcoming": {"name": "Paracetamol (Local)", "dosage": "500mg", "time": f"{next_hour:02d}:00", "slot": 1},
        "today": [
            {"name": "Antibiotic (Local)", "dosage": "250mg", "time": "08:00", "slot": 2, "status": "taken"},
            {"name": "Paracetamol (Local)", "dosage": "500mg", "time": f"{next_hour:02d}:00", "slot": 1, "status": "upcoming"}
        ]})

@app.route('/connection_status', methods=['GET'])
def connection_status_endpoint():
    return jsonify({"server_connected": connection_status["connected"], "server_url": LLM_SERVER_URL, "client_ip": local_ip})

if __name__ == '__main__':
    logger.info(f"Starting Raspberry Pi client (IP: {local_ip})")
    logger.info(f"Connecting to LLM server at: {LLM_SERVER_URL}")

    # Explicitly check and log telegram library status
    if telegram is None:
        logger.error("FATAL STARTUP ERROR: 'python-telegram-bot' library object is None (Import failed).")
        TELEGRAM_ENABLED = False
    else:
        logger.info("'python-telegram-bot' library appears to be imported successfully.")

    logger.info(f"Telegram notifications are {'ENABLED' if TELEGRAM_ENABLED else 'DISABLED'} after import check.")

    if TELEGRAM_ENABLED:
        if TELEGRAM_BOT_TOKEN == "YOUR_ACTUAL_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN is not set or is a placeholder. Telegram notifications will likely fail even if library is loaded.")
        if TELEGRAM_CHAT_ID == "YOUR_ACTUAL_CHAT_ID" or not TELEGRAM_CHAT_ID:
            logger.warning("TELEGRAM_CHAT_ID is not set or is a placeholder. Telegram notifications will likely fail even if library is loaded.")
        
        # Test Telegram connection at startup
        try:
            test_telegram_connection()
        except Exception as e:
            logger.error(f"Telegram test failed with unexpected error: {e}", exc_info=True)
    
    initial_connection = check_server_connection()
    connection_status["connected"] = initial_connection

    if initial_connection:
        if not register_with_server():
             logger.warning("Initial registration with server failed despite connection.")
        else:
            logger.info("Server connected and client registered. Operating in connected mode.")
    else:
        logger.warning("Could not connect to LLM server. Operating in standalone mode.")
    
    connection_thread = threading.Thread(target=periodic_connection_check, daemon=True, name="ConnectionCheckThread")
    connection_thread.start()
    logger.info("Connection monitoring thread started.")
    
    if TELEGRAM_ENABLED:
        medication_thread = threading.Thread(target=check_missed_medications, daemon=True, name="MedicationMonitorThread")
        medication_thread.start()
        logger.info("Medication monitoring thread started.")
    else:
        logger.info("Medication monitoring thread NOT started as Telegram is disabled (likely due to import error or configuration).")
        
    try:
        logger.info(f"Flask app starting on host 0.0.0.0, port 5001. Debug: True, Reloader: False")
        app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
    except Exception as e:
        logger.critical(f"Flask app failed to start or crashed: {e}", exc_info=True)
    finally:
        logger.info("Application shutting down...")
        hardware.cleanup()
        logger.info("Application shutdown complete. Cleaned up hardware resources.")
