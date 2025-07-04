
-----

# Zima Pharma - Smart Pill Dispenser with LLM Assistant

Zima Pharma is a proof-of-concept smart pill dispenser system that uses a locally-run Large Language Model (Ollama) to provide a natural language interface for managing medication, controlling hardware, and sending caregiver alerts.

The system consists of a central Python server that handles language processing and a client that runs on a Raspberry Pi to control the physical dispensing mechanism.

<img width="468" alt="image" src="https://github.com/user-attachments/assets/3b0ddf57-ce53-4e86-b10b-bcf41a6a854c" />



## Features

  - **Conversational AI:** Interact with the dispenser using natural language commands thanks to the Ollama LLM integration.
  - **Hardware Control:** Accurately dispenses pills by controlling servo motors.
  - **Pill Pickup Detection:** Uses an ultrasonic sensor to verify if a dispensed pill has been taken.
  - **Caregiver Alerts:** Sends timely notifications via Telegram for missed medications or emergency events.
  - **User Profile Management:** Tracks user-specific medical history and medication schedules.
  - **Offline Fallback:** The Raspberry Pi client can perform core functions even if the connection to the LLM server is lost.
  - **Web Interface:** A simple, clean web UI for chat, manual control, and system status monitoring.
  - **Function Calling:** The LLM can intelligently trigger hardware actions (like dispensing or getting weather) based on the conversation.

## Technology Stack

  - **Backend:** Python, Flask
  - **LLM:** Ollama with the `deepseek-r1:8b` model
  - **Hardware:** Raspberry Pi (3B+ or newer recommended)
  - **Actuators & Sensors:** SG90 Servo Motors, HC-SR04 Ultrasonic Sensor
  - **Notifications:** Telegram
  - **Core Libraries:** `requests`, `RPi.GPIO`, `python-telegram-bot`

-----

## Setup and Installation

This project requires setting up two components: the **LLM Server** on a host machine (like a laptop) and the **Client** on a Raspberry Pi.

### Prerequisites

1.  **Python:** Ensure Python 3.8+ is installed on both machines.
2.  **Ollama:** Install Ollama on the server machine. [Download from ollama.com](https://ollama.com/).
3.  **Git:** Install Git for cloning the repository.
4.  **API Keys:**
      - **OpenWeatherMap:** Get a free API key to enable weather forecasts.
      - **Telegram:** Create a new bot using `@BotFather` on Telegram to get a Bot Token and your Chat ID.

### Step 1: LLM Server Setup (On your Mac/PC/Linux machine)

This machine will run the LLM and act as the "brain" of the system.

1.  **Clone the repository:**

    ```bash
    git clone <your-repository-url>
    cd <repository-folder>
    ```

2.  **Set up Ollama and pull the model:**
    After installing Ollama, run the following command in your terminal to download the required model. The server script will also try to do this automatically if the model is missing.

    ```bash
    ollama pull deepseek-r1:8b
    ```

3.  **Create a virtual environment and install dependencies:**

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install Flask requests Flask-Cors
    ```

4.  **Run the server:**

    ```bash
    python serverollamamac.py
    ```

    The server will start on `http://0.0.0.0:5000`. Note down the local IP address of this machine (e.g., `192.168.1.104`), as you will need it for the client setup.

### Step 2: Raspberry Pi Client Setup

This is the hardware controller.

1.  **Hardware Connections:**
    Connect the servos and ultrasonic sensor to the Raspberry Pi's GPIO pins.

    | Component | Pi Pin (BCM) |
    | :--- | :--- |
    | Servo 1 (VCC) | 5V |
    | Servo 1 (GND) | GND |
    | Servo 1 (Signal) | GPIO 12 |
    | Servo 2 (VCC) | 5V |
    | Servo 2 (GND) | GND |
    | Servo 2 (Signal) | GPIO 23 |
    | HC-SR04 (VCC) | 5V |
    | HC-SR04 (GND) | GND |
    | HC-SR04 (Trig) | GPIO 21 |
    | HC-SR04 (Echo) | GPIO 20 |

2.  **Clone the repository on the Raspberry Pi:**

    ```bash
    git clone <your-repository-url>
    cd <repository-folder>
    ```

3.  **Create a virtual environment and install dependencies:**

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install Flask requests RPi.GPIO python-telegram-bot
    ```

4.  **Configure the Client Script (`llmzima.py`):**
    This is the most important step. Open `llmzima.py` in an editor and update the following configuration variables:

    ```python
    # LLM Server configuration (REPLACE WITH YOUR SERVER'S IP)
    LLM_SERVER_URL = "yoururl"

    # OpenWeatherMap API configuration (REPLACE WITH YOUR KEY)
    OPENWEATHER_API_KEY = "youkey"

    # --- IMPORTANT TELEGRAM CONFIGURATION ---
    TELEGRAM_BOT_TOKEN = "youkey"  # <<< --- !!! REPLACE THIS !!!
    TELEGRAM_CHAT_ID = "yours"  # <<< --- !!! REPLACE THIS !!!
    ```

5.  **Run the client:**

    ```bash
    # Use sudo if GPIO access requires it
    sudo python llmzima.py
    ```

    The client will start, attempt to connect to the server, and become ready for commands.

## Usage

Once both the server and client are running:

1.  Open a web browser and navigate to the Raspberry Pi's IP address on port 5001 (e.g., `http://192.168.1.150:5001`).
2.  The web interface will load, showing the chat window, medication schedule, and manual controls.
3.  You can now interact with the system by typing messages in the chat box.

#### Example Commands:

  - `"What's the weather like today?"`
  - `"I have a headache."`
  - `"Dispense the antibiotic from slot 2."`
  - `"Did I take my pill?"` (This will trigger the distance sensor)
  - `"Rotate servo 1 clockwise."`

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
