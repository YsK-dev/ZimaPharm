# serverollamamac.py

from flask import Flask, request, jsonify, render_template
import os
import json
import logging
import time
from datetime import datetime
from flask_cors import CORS
import requests
import subprocess
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("llm_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Ollama configuration
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "deepseek-r1:8b"

# Data storage paths
DATA_DIR = os.path.join(os.path.expanduser("~"), "zima_data")
USERS_DIR = os.path.join(DATA_DIR, "users")



# Ensure directories exist
os.makedirs(USERS_DIR, exist_ok=True)

# Client registration tracking
registered_clients = {}

# Chat history
chat_history = []

# Available function calls that clients can make
AVAILABLE_FUNCTIONS = {
    "get_weather_data": {
        "description": "Get current weather information for a city",
        "parameters": {
            "city": {"type": "string", "description": "City name"},
            "units": {"type": "string", "description": "Temperature units (metric, imperial, kelvin)", "default": "metric"}
        }
    },
    "rotate_servo_90_degrees": {
        "description": "Rotate a servo motor by 90 degrees",
        "parameters": {
            "servo_num": {"type": "integer", "description": "Servo number (1 or 2)"},
            "direction": {"type": "string", "description": "Rotation direction (clockwise or counterclockwise)", "default": "clockwise"}
        }
    },
    "dispense_pill": {
        "description": "Dispense medication from a specific compartment",
        "parameters": {
            "compartment": {"type": "integer", "description": "Compartment number (1 or 2)"}
        }
    },
    "measure_distance": {
        "description": "Measure distance using ultrasonic sensor to check pill pickup",
        "parameters": {}
    }
}

# Ensure Ollama is running with deepseek-r1 model
def setup_ollama():
    """Check if Ollama is running and the deepseek-r1 model is available"""
    try:
        # Check if Ollama is running
        response = requests.get(f"{OLLAMA_HOST}/api/tags")
        if response.status_code != 200:
            logger.error("Ollama server not running. Please start Ollama.")
            return False
        
        # Check if deepseek-r1 model is available
        models = response.json().get("models", [])
        model_names = [model.get("name") for model in models]
        
        if OLLAMA_MODEL not in model_names:
            logger.warning(f"{OLLAMA_MODEL} model not found. Pulling model...")
            # Try to pull the model
            pull_process = subprocess.Popen(
                ["ollama", "pull", OLLAMA_MODEL],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Log the pull process output
            for line in pull_process.stdout:
                logger.info(f"Ollama pull: {line.strip()}")
                
            # Wait for the process to complete
            pull_process.wait()
            
            if pull_process.returncode != 0:
                logger.error(f"Failed to pull {OLLAMA_MODEL} model")
                return False
            
            logger.info(f"Successfully pulled {OLLAMA_MODEL} model")
            
        logger.info(f"Ollama setup complete. {OLLAMA_MODEL} model is available.")
        return True
    except Exception as e:
        logger.error(f"Error setting up Ollama: {e}")
        return False

# Replace the detect_function_calls function (around line 110)

def detect_function_calls(user_input):
    """Detect if the user input requires function calls"""
    user_input_lower = user_input.lower()
    function_calls = []
    
    # Weather function detection - IMPROVED
    if any(word in user_input_lower for word in ["weather", "temperature", "forecast", "rain", "sunny", "cloudy"]):
        # Extract city if mentioned - BETTER LOGIC
        city = "London"  # Default city
        words = user_input.split()
        
        # Look for city names after prepositions or directly mentioned
        for i, word in enumerate(words):
            word_clean = word.lower().strip('?.,!')
            if word_clean in ["in", "for", "at"] and i + 1 < len(words):
                city = words[i + 1].strip('?.,!').title()
                break
            elif word_clean in ["london", "paris", "tokyo", "newyork", "sydney", "berlin"]:
                city = word_clean.title()
                break
        
        logger.info(f"Weather function detected for city: {city}")
        function_calls.append({
            "function": "get_weather_data",
            "args": {"city": city, "units": "metric"}
        })
    
    # Servo rotation function detection
    if any(word in user_input_lower for word in ["rotate", "turn", "servo", "motor"]):
        servo_num = 1
        direction = "clockwise"
        
        if "2" in user_input_lower or "two" in user_input_lower:
            servo_num = 2
        if "counter" in user_input_lower or "anti" in user_input_lower or "left" in user_input_lower:
            direction = "counterclockwise"
            
        logger.info(f"Servo function detected: servo {servo_num}, direction {direction}")
        function_calls.append({
            "function": "rotate_servo_90_degrees",
            "args": {"servo_num": servo_num, "direction": direction}
        })
    
    # Pill dispensing function detection
    if any(word in user_input_lower for word in ["dispense", "give", "take", "pill", "medication"]):
        compartment = None
        if "paracetamol" in user_input_lower or "slot 1" in user_input_lower or "compartment 1" in user_input_lower:
            compartment = 1
        elif "antibiotic" in user_input_lower or "slot 2" in user_input_lower or "compartment 2" in user_input_lower:
            compartment = 2
            
        if compartment:
            logger.info(f"Dispense function detected for compartment {compartment}")
            function_calls.append({
                "function": "dispense_pill",
                "args": {"compartment": compartment}
            })
    
    # Distance measurement function detection
    if any(word in user_input_lower for word in ["distance", "measure", "pickup", "check pill"]):
        logger.info("Distance measurement function detected")
        function_calls.append({
            "function": "measure_distance",
            "args": {}
        })
    
    logger.info(f"Detected {len(function_calls)} function calls: {[f['function'] for f in function_calls]}")
    return function_calls

def execute_function_call(function_name, args, client_ip):
    """Execute a function call on the appropriate client"""
    if client_ip not in registered_clients:
        return {"success": False, "error": "Client not registered"}
    
    try:
        # Make a request to the client to execute the function
        client_data = registered_clients[client_ip]
        client_url = f"http://{client_ip}:5001"
        
        if function_name in ["get_weather_data"]:
            # Weather data can be called directly on the client
            response = requests.post(f"{client_url}/function_call", 
                                   json={"function_name": function_name, "args": args}, 
                                   timeout=10)
        elif function_name == "rotate_servo_90_degrees":
            # Servo rotation
            response = requests.post(f"{client_url}/servo_rotate", 
                                   json=args, 
                                   timeout=10)
        elif function_name == "dispense_pill":
            # Pill dispensing
            response = requests.post(f"{client_url}/dispense/{args['compartment']}", 
                                   timeout=10)
        elif function_name == "measure_distance":
            # Distance measurement
            response = requests.get(f"{client_url}/distance", timeout=10)
        else:
            return {"success": False, "error": f"Unknown function: {function_name}"}
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"Client returned status {response.status_code}"}
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error executing function {function_name} on client {client_ip}: {e}")
        return {"success": False, "error": f"Failed to communicate with client: {str(e)}"}

## Replace the generate_response function (around line 240)

def generate_response(prompt, system_prompt=None, user_id=None, client_ip=None):
    """Generate a response using Ollama API with the deepseek-r1 model"""
    try:
        # FIXED: Extract just the user message for function detection
        # Look for "User request:" in the prompt to get the actual user input
        user_message = prompt
        if "User request:" in prompt:
            user_message = prompt.split("User request:")[-1].split("\n\n")[0].strip()
        
        logger.info(f"Extracted user message for function detection: '{user_message}'")
        
        # Detect function calls in the user input ONLY
        function_calls = detect_function_calls(user_message)
        function_results = []
        
        # Execute detected function calls
        if function_calls and client_ip:
            logger.info(f"Executing {len(function_calls)} function calls on client {client_ip}")
            for func_call in function_calls:
                result = execute_function_call(func_call["function"], func_call["args"], client_ip)
                function_results.append({
                    "function": func_call["function"],
                    "args": func_call["args"],
                    "result": result
                })
                logger.info(f"Function {func_call['function']} result: {result}")
        
        # Build the request data
        data = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        # Enhanced system prompt for medical context with function calling
        enhanced_system_prompt = """You are an assistant for a smart pill dispenser system called Zima Pharma.
        The system has two medication slots:
        - Slot 1 contains Paracetamol (500mg) for pain and fever
        - Slot 2 contains Antibiotics (250mg) that should be taken with food
        
        You can perform the following actions:
        1. Get weather information for any city
        2. Control servo motors (rotate 90 degrees clockwise or counterclockwise)
        3. Dispense medication from compartments
        4. Measure distance to check pill pickup
        
        When users ask about weather, servo control, or medication dispensing, I will execute the appropriate functions.
        Always provide helpful medical information and remind users about proper medication usage.
        For emergencies or serious medical concerns, advise users to contact a healthcare professional.
        """
        
        # Add system prompt
        if system_prompt:
            data["system"] = system_prompt
        else:
            data["system"] = enhanced_system_prompt
        
        # If we have function results, include them in the context
        if function_results:
            function_context = "\n\nFunction execution results:\n"
            for result in function_results:
                function_context += f"- {result['function']}({result['args']}): {result['result']}\n"
            data["prompt"] = prompt + function_context + "\n\nPlease respond based on the function results above."
        
        # Make the API call to Ollama
        logger.debug(f"Sending request to Ollama: {prompt[:50]}...")
        response = requests.post(f"{OLLAMA_HOST}/api/generate", json=data)
        
        if response.status_code == 200:
            result = response.json()
            generated_text = result.get("response", "")
            logger.debug(f"Ollama response: {generated_text[:50]}...")
            return generated_text
        else:
            logger.error(f"Ollama API error: {response.status_code}")
            return "I'm having trouble processing your request. Please try again later."
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "Sorry, I encountered an error. Please try again."
# User data management
def load_users():
    """Load all users from the users directory"""
    users = []
    try:
        if not os.path.exists(USERS_DIR):
            return {"users": []}
            
        for filename in os.listdir(USERS_DIR):
            if filename.endswith(".json"):
                user_id = filename.split(".")[0]
                user_data = load_user_data(user_id)
                if user_data:
                    users.append(user_data)
        return {"users": users}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {"users": []}

def load_user_data(user_id):
    """Load a specific user's data"""
    try:
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        if os.path.exists(user_file):
            with open(user_file, 'r') as f:
                return json.load(f)
        return None
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None

def save_user_data(user_id, user_data):
    """Save a user's data to file"""
    try:
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        with open(user_file, 'w') as f:
            json.dump(user_data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")
        return False

def get_next_user_id():
    """Generate the next available user ID"""
    try:
        user_ids = []
        for filename in os.listdir(USERS_DIR):
            if filename.endswith(".json"):
                user_id = filename.split(".")[0]
                try:
                    user_ids.append(int(user_id))
                except ValueError:
                    pass
        return str(max(user_ids) + 1 if user_ids else 1)
    except Exception as e:
        logger.error(f"Error generating next user ID: {e}")
        return "1"

# Flask routes for client-server communication
@app.route('/api/heartbeat', methods=['GET'])
def heartbeat():
    """Simple heartbeat endpoint to check if server is alive"""
    client_ip = request.remote_addr
    logger.debug(f"Heartbeat request from {client_ip}")
    return jsonify({
        "status": "ok", 
        "server_time": datetime.now().isoformat(),
        "clients_count": len(registered_clients)
    })

@app.route('/api/register_client', methods=['POST'])
def register_client():
    """Allow Raspberry Pi clients to register with this server"""
    client_data = request.json
    client_ip = request.remote_addr
    
    if not client_data:
        logger.warning(f"Empty client registration from {client_ip}")
        return jsonify({"success": False, "error": "No client data provided"}), 400
    
    client_data['last_seen'] = datetime.now().isoformat()
    registered_clients[client_ip] = client_data
    
    logger.info(f"Client registered: {client_ip} ({client_data.get('client_type', 'unknown')})")
    logger.info(f"Total registered clients: {len(registered_clients)}")
    
    return jsonify({
        "success": True, 
        "message": "Client registered successfully",
        "client_ip": client_ip,
        "server_time": datetime.now().isoformat()
    })

@app.route('/api/clients', methods=['GET'])
def list_clients():
    """List all registered clients"""
    return jsonify({
        "success": True,
        "clients": registered_clients,
        "count": len(registered_clients)
    })

@app.route('/api/available_functions', methods=['GET'])
def get_available_functions():
    """Return available function calls"""
    client_ip = request.remote_addr
    logger.debug(f"Available functions request from {client_ip}")
    
    return jsonify({
        "success": True,
        "functions": AVAILABLE_FUNCTIONS
    })

# Replace the existing chat function (around line 430)

@app.route('/api/chat', methods=['POST'])
@app.route('/chat', methods=['POST'])  # Support both with and without /api prefix
def chat():
    data = request.get_json()
    user_input = data.get('message', '')
    user_id = data.get('user_id', '1')
    client_ip = request.remote_addr
    
    logger.info(f"Chat request from {client_ip}: User {user_id} - '{user_input}'")
    
    # Get user data for context
    user_data = load_user_data(user_id)
    
    # Build context for the LLM
    context = ""
    if user_data:
        name = user_data.get("personal", {}).get("name", "Unknown")
        age = user_data.get("personal", {}).get("age", "Unknown")
        conditions = user_data.get("medical_history", {}).get("conditions", [])
        allergies = user_data.get("medical_history", {}).get("allergies", [])
        medications = user_data.get("medications", [])
        
        context = f"User: {name}, Age: {age}\n"
        if conditions:
            context += f"Medical conditions: {', '.join(conditions)}\n"
        if allergies:
            context += f"Allergies: {', '.join(allergies)}\n"
        if medications:
            context += "Current medications:\n"
            for med in medications:
                context += f"- {med.get('name', 'Unknown')} ({med.get('dosage', 'Unknown')}) in slot {med.get('slot', 'Unknown')}\n"
    
    # Create a prompt with context
    full_prompt = f"{context}\n\nUser request: {user_input}\n\nPlease respond to the user's request considering their medical information above."
    
    # FIXED: Find a registered client for function calling
    target_client = None
    if registered_clients:
        # Prefer the requesting client if it's registered, otherwise use any available client
        if client_ip in registered_clients:
            target_client = client_ip
        else:
            target_client = list(registered_clients.keys())[0]
        logger.info(f"Using target client: {target_client} for function calls")
    else:
        logger.warning("No registered clients available for function calling")
    
    # Generate response from Ollama with function calling support
    response = generate_response(full_prompt, user_id=user_id, client_ip=target_client)
    
    logger.info(f"Response to {client_ip}: '{response[:50]}...'")
    
    return jsonify({
        "success": True,
        "response": response
    })

# ADDED: Manual servo control endpoints
@app.route('/api/servo_rotate', methods=['POST'])
def servo_rotate():
    """Manual servo rotation endpoint"""
    data = request.get_json()
    client_ip = request.remote_addr
    
    servo_num = data.get('servo_num', 1)
    direction = data.get('direction', 'clockwise')
    
    logger.info(f"Servo rotate request from {client_ip}: Servo {servo_num} {direction}")
    
    # Find a registered client to execute the servo function
    if not registered_clients:
        return jsonify({
            "success": False,
            "error": "No clients available",
            "message": "No Raspberry Pi clients are currently connected"
        }), 503
    
    # Use the first available client or the requesting client if registered
    target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
    
    result = execute_function_call("rotate_servo_90_degrees", {
        "servo_num": servo_num,
        "direction": direction
    }, target_client)
    
    return jsonify(result)

@app.route('/api/servo_position/<int:servo_num>', methods=['GET'])
def get_servo_position(servo_num):
    """Get current servo position"""
    client_ip = request.remote_addr
    logger.debug(f"Servo position request from {client_ip} for servo {servo_num}")
    
    if servo_num not in [1, 2]:
        return jsonify({
            "success": False,
            "error": "Invalid servo number. Must be 1 or 2"
        }), 400
    
    # Find a registered client to get servo position
    if not registered_clients:
        return jsonify({
            "success": False,
            "error": "No clients available",
            "message": "No Raspberry Pi clients are currently connected"
        }), 503
    
    # Use the first available client or the requesting client if registered
    target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
    
    try:
        client_url = f"http://{target_client}:5001"
        response = requests.get(f"{client_url}/servo_position/{servo_num}", timeout=10)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({
                "success": False,
                "error": f"Client returned status {response.status_code}",
                "position": 0  # Default fallback
            })
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting servo {servo_num} position from client {target_client}: {e}")
        return jsonify({
            "success": False,
            "error": f"Failed to communicate with client: {str(e)}",
            "position": 0  # Default fallback
        })

@app.route('/api/dispense/<int:slot>', methods=['POST'])
def dispense_pill_manual():
    """Manual pill dispensing endpoint"""
    client_ip = request.remote_addr
    
    if slot not in [1, 2]:
        return jsonify({
            "success": False,
            "error": "Invalid slot number. Must be 1 or 2"
        }), 400
    
    logger.info(f"Manual pill dispense request from {client_ip}: Slot {slot}")
    
    # Find a registered client to execute the dispense function
    if not registered_clients:
        return jsonify({
            "success": False,
            "error": "No clients available",
            "message": "No Raspberry Pi clients are currently connected"
        }), 503
    
    # Use the first available client or the requesting client if registered
    target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
    
    result = execute_function_call("dispense_pill", {"compartment": slot}, target_client)
    return jsonify(result)

@app.route('/api/check_pill_pickup', methods=['GET'])
@app.route('/check_pill_pickup', methods=['GET'])  # Support both with and without /api prefix
def check_pill_pickup():
    """Check pill pickup using distance sensor"""
    client_ip = request.remote_addr
    logger.debug(f"Pill pickup check request from {client_ip}")
    
    # Find a registered client to check distance
    if not registered_clients:
        return jsonify({
            "success": False,
            "error": "No clients available",
            "distance_cm": 999  # Default high value
        }), 503
    
    # Use the first available client or the requesting client if registered
    target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
    
    result = execute_function_call("measure_distance", {}, target_client)
    
    # Ensure we always return a distance_cm value for the UI
    if not result.get("success", False):
        result["distance_cm"] = 999  # Default high value when sensor fails
    
    return jsonify(result)

@app.route('/api/emergency', methods=['POST'])
def emergency_alert():
    """Send emergency alert"""
    client_ip = request.remote_addr
    logger.warning(f"EMERGENCY ALERT from {client_ip}")
    
    try:
        # Log emergency
        emergency_log = {
            "timestamp": datetime.now().isoformat(),
            "client_ip": client_ip,
            "type": "manual_emergency_button",
            "status": "logged"
        }
        
        logger.critical(f"EMERGENCY: {emergency_log}")
        
        # Notify all registered clients about the emergency
        for client_ip_registered, client_data in registered_clients.items():
            try:
                client_url = f"http://{client_ip_registered}:5001"
                requests.post(f"{client_url}/emergency_alert", 
                             json=emergency_log, 
                             timeout=5)
            except:
                pass  # Don't fail if clients can't be notified
        
        return jsonify({
            "success": True,
            "message": "Emergency alert has been sent",
            "timestamp": emergency_log["timestamp"]
        })
        
    except Exception as e:
        logger.error(f"Error processing emergency alert: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to process emergency alert"
        }), 500

@app.route('/api/users', methods=['GET'])
def get_users():
    client_ip = request.remote_addr
    logger.debug(f"Users list request from {client_ip}")
    
    try:
        users_data = load_users()
        users = users_data.get('users', [])
        
        return jsonify({
            "success": True,
            "users": users
        })
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/users/save', methods=['POST'])
def save_user():
    data = request.get_json()
    user_id = data.get('user_id')
    user_data = data.get('user_data')
    client_ip = request.remote_addr
    
    if not user_id or not user_data:
        logger.warning(f"Invalid user save request from {client_ip}: Missing data")
        return jsonify({
            "success": False,
            "error": "Missing user_id or user_data"
        }), 400
    
    logger.info(f"Saving user {user_id} data from {client_ip}")
    success = save_user_data(user_id, user_data)
    
    if success:
        return jsonify({
            "success": True
        })
    else:
        return jsonify({
            "success": False,
            "error": "Failed to save user data"
        }), 500

@app.route('/api/select_user', methods=['POST'])
def select_user():
    user_id = request.json.get('user_id', '')
    client_ip = request.remote_addr
    
    logger.debug(f"User selection request from {client_ip}: User ID {user_id}")
    user_data = load_user_data(user_id)
    
    if user_data:
        return jsonify({
            "success": True,
            "user": user_data
        })
    else:
        logger.warning(f"User not found for {client_ip}: User ID {user_id}")
        return jsonify({
            "success": False,
            "error": "User not found"
        }), 404

@app.route('/api/add_user', methods=['POST'])
def add_user():
    client_ip = request.remote_addr
    
    try:
        # Get new user data from request
        new_user_data = request.json
        
        # Generate new user ID
        new_id = get_next_user_id()
        
        # Add ID to new user data
        new_user_data['id'] = new_id
        
        logger.info(f"Adding new user from {client_ip}: ID {new_id}, Name: {new_user_data.get('personal', {}).get('name', 'Unknown')}")
        
        # Save to file
        if not save_user_data(new_id, new_user_data):
            return jsonify({
                "success": False,
                "error": "Could not save user data"
            }), 500
        
        return jsonify({
            "success": True,
            "user_id": new_id
        })
    except Exception as e:
        logger.error(f"Error adding user from {client_ip}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/get_medication_info/<int:slot>', methods=['GET'])
def get_medication_info(slot):
    client_ip = request.remote_addr
    logger.debug(f"Medication info request from {client_ip} for slot {slot}")
    
    if slot == 1:
        return jsonify({
            "success": True,
            "name": "Paracetamol",
            "dosage": "500mg",
            "schedule": "As needed",
            "description": "Use for pain or fever. Do not exceed 8 tablets in 24 hours.",
            "icon": "bi-capsule"
        })
    elif slot == 2:
        return jsonify({
            "success": True,
            "name": "Antibiotic",
            "dosage": "250mg", 
            "schedule": "Every 8 hours",
            "description": "Take with food. Complete the full course of treatment.",
            "icon": "bi-pill"
        })
    else:
        logger.warning(f"Invalid slot request from {client_ip}: Slot {slot}")
        return jsonify({
            "success": False,
            "error": "Invalid slot number"
        }), 400

@app.route('/api/get_schedule', methods=['GET'])
def get_schedule():
    client_ip = request.remote_addr
    logger.debug(f"Schedule request from {client_ip}")
    
    # In a real app, this would retrieve data from a database
    now = datetime.now()
    next_hour = (now.hour + 1) % 24
    
    return jsonify({
        "success": True,
        "upcoming": {
            "name": "Paracetamol",
            "dosage": "500mg",
            "time": f"{next_hour:02d}:00",
            "slot": 1
        },
        "today": [
            {
                "name": "Antibiotic",
                "dosage": "250mg",
                "time": "08:00",
                "slot": 2,
                "status": "taken"
            },
            {
                "name": "Paracetamol",
                "dosage": "500mg",
                "time": f"{next_hour:02d}:00",
                "slot": 1,
                "status": "upcoming"
            }
        ]
    })

@app.route('/api/execute_function', methods=['POST'])
def execute_function():
    """Execute a function on a specific client"""
    data = request.json
    function_name = data.get('function_name')
    args = data.get('args', {})
    target_client = data.get('client_ip')
    
    if not function_name:
        return jsonify({
            "success": False,
            "error": "Missing function_name"
        }), 400
    
    if not target_client:
        # Use the requesting client if no target specified
        target_client = request.remote_addr
    
    if target_client not in registered_clients:
        return jsonify({
            "success": False,
            "error": "Target client not registered"
        }), 404
    
    result = execute_function_call(function_name, args, target_client)
    return jsonify(result)

@app.route('/api/weather', methods=['GET'])
def get_weather_proxy():
    """Proxy weather requests to the appropriate client"""
    city = request.args.get('city', 'London')
    units = request.args.get('units', 'metric')
    client_ip = request.remote_addr
    
    # Find a registered client to execute the weather function
    if not registered_clients:
        return jsonify({
            "success": False,
            "error": "No clients available"
        }), 503
    
    # Use the first available client or the requesting client if registered
    target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
    
    result = execute_function_call("get_weather_data", {"city": city, "units": units}, target_client)
    return jsonify(result)

@app.route('/api/system_status', methods=['GET'])
def system_status():
    """Return system status information"""
    client_ip = request.remote_addr
    logger.debug(f"System status request from {client_ip}")
    
    # Check Ollama status
    ollama_status = "offline"
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags")
        if response.status_code == 200:
            ollama_status = "online"
    except:
        pass
    
    # Basic system info - could be expanded with more details
    return jsonify({
        "success": True,
        "server": {
            "status": "online",
            "uptime": "unknown",  # Would need to track server start time
            "version": "1.0",
            "registered_clients": len(registered_clients)
        },
        "llm": {
            "status": ollama_status,
            "model": OLLAMA_MODEL
        },
        "storage": {
            "users_count": len(load_users().get("users", [])),
            "data_dir": DATA_DIR
        },
        "functions": {
            "available": list(AVAILABLE_FUNCTIONS.keys()),
            "count": len(AVAILABLE_FUNCTIONS)
        }
    })

# ADDED: Main web interface route
@app.route('/')
def index():
    """Serve the main web interface"""
    try:
        # Load users for the dropdown
        users_data = load_users()
        users = users_data.get('users', [])
        
        # For demo purposes, select first user if available
        current_user_id = users[0]['id'] if users else None
        current_user_data = load_user_data(current_user_id) if current_user_id else {}
        
        # Prepare user options for the select dropdown
        user_options = []
        for user in users:
            user_options.append({
                'id': user['id'],
                'name': user.get('personal', {}).get('name', 'Unknown User')
            })
        
        return render_template('index.html',
                             user_data=current_user_data,
                             current_user=current_user_id,
                             user_options=user_options,
                             chat_history=[])  # Empty for now, could load from file
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return f"Error loading page: {str(e)}", 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "message": "The requested API endpoint does not exist"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "message": "An unexpected error occurred on the server"
    }), 500
# Add this route after the other API endpoints (around line 900)

@app.route('/api/debug/routes', methods=['GET'])
def debug_routes():
    """Debug endpoint to see all registered routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            "endpoint": rule.endpoint,
            "methods": list(rule.methods),
            "rule": str(rule)
        })
    
    return jsonify({
        "success": True,
        "total_routes": len(routes),
        "routes": sorted(routes, key=lambda x: x["rule"]),
        "chat_routes": [r for r in routes if "chat" in r["rule"].lower()]
    })

# Add this after the debug_routes function (around line 930)

@app.route('/simple_chat', methods=['POST'])
def simple_chat_fallback():
    """Fallback chat endpoint for debugging"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data"}), 400
        
        user_input = data.get('message', '')
        user_id = data.get('user_id', '1')
        client_ip = request.remote_addr
        
        logger.info(f"FALLBACK chat from {client_ip}: '{user_input}'")
        
        if not user_input:
            return jsonify({"success": False, "error": "Empty message"}), 400
        
        # Try to find a registered client for function calling
        target_client = None
        if registered_clients:
            target_client = client_ip if client_ip in registered_clients else list(registered_clients.keys())[0]
        
        # Generate response using the same function as main chat
        response_text = generate_response(user_input, user_id=user_id, client_ip=target_client)
        
        return jsonify({
            "success": True,
            "response": response_text,
            "debug_info": {
                "client_ip": client_ip,
                "user_id": user_id,
                "registered_clients": len(registered_clients),
                "target_client": target_client
            }
        })
        
    except Exception as e:
        logger.error(f"Error in simple_chat_fallback: {e}")
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

# Fix the request logging
@app.before_request
def log_request_info():
    """Log incoming chat requests for debugging"""
    if request.method == 'POST' and 'chat' in request.path:
        logger.info(f"Chat request: {request.method} {request.path} from {request.remote_addr}")

# Periodic cleanup of inactive clients
def cleanup_inactive_clients():
    """Remove clients that haven't been seen for more than 10 minutes"""
    now = datetime.now()
    inactive_threshold = 600  # 10 minutes in seconds
    
    to_remove = []
    for client_ip, client_data in registered_clients.items():
        last_seen = datetime.fromisoformat(client_data.get('last_seen', '2000-01-01T00:00:00'))
        if (now - last_seen).total_seconds() > inactive_threshold:
            to_remove.append(client_ip)
    
    for client_ip in to_remove:
        logger.info(f"Removing inactive client: {client_ip}")
        del registered_clients[client_ip]
    
    if to_remove:
        logger.info(f"Removed {len(to_remove)} inactive clients. {len(registered_clients)} active clients remaining.")

if __name__ == '__main__':
    # Get server's IP address for logging
    server_ip = "127.0.0.1"  # Default
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
    except Exception as e:
        logger.error(f"Could not determine server IP: {e}")
    
    logger.info("=" * 50)
    logger.info(f"Starting Enhanced LLM server on Mac (IP: {server_ip})")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Ollama model: {OLLAMA_MODEL}")
    logger.info(f"Available functions: {list(AVAILABLE_FUNCTIONS.keys())}")
    logger.info(f"Server accessible at: http://{server_ip}:5000/")
    logger.info("=" * 50)
    
    # Set up Ollama
    if not setup_ollama():
        logger.warning("Continuing without Ollama LLM integration. Responses will be generic.")
    
    # Set up background task for client cleanup
    def run_periodic_cleanup():
        while True:
            time.sleep(300)  # Check every 5 minutes
            cleanup_inactive_clients()
    
    cleanup_thread = threading.Thread(target=run_periodic_cleanup, daemon=True)
    cleanup_thread.start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000)