from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import os
from datetime import datetime
import openai
from openai import OpenAI, OpenAIError
from packaging import version
import json
from time import sleep
from ratelimit import limits, sleep_and_retry, RateLimitException
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import re
from threading import Lock

# Create a lock for managing concurrent access to the OpenAI API
openai_lock = Lock()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///data.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Set API key and check OpenAI version
os.environ["OPENAI_API_KEY"] = ""
required_version = version.parse("1.1.1")
current_version = version.parse(openai.__version__)
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
if current_version < required_version:
    raise ValueError(
        f"Error: OpenAI version {openai.__version__} is less than the required version 1.1.1"
    )
else:
    print("OpenAI version is compatible.")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Define the rate limit: 500 RPM translates to roughly 8.3 RPS
# You may choose to use a slightly lower limit to add a safety margin
GPT4_RATE_LIMIT_REQUESTS = 8
GPT4_RATE_LIMIT_PERIOD = 1  # In seconds

GPT3_RATE_LIMIT_REQUESTS = 58
GPT3_RATE_LIMIT_PERIOD = 1  # In seconds


def rate_limit_logger(fn):
    """
    A decorator to log when the rate limit has been reached.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            # Log the rate limit hit before sleep_and_retry takes effect
            print("Rate limit REACHED")
            raise e  # Reraise the exception to ensure sleep_and_retry can catch it
    return wrapper

# Models
class FeedbackData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.String(2000), nullable=False)
    feedback = db.Column(db.String(100), default="non-rated")
    username =db.Column(db.String(100), default="non-existent")
    user_type =db.Column(db.String(100), default="none")
    thread_type =db.Column(db.String(100), default="none")
    thread_id =db.Column(db.String(100), default="none")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class UserData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(500), nullable=False)
    password = db.Column(db.String(2000), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    newsletter = db.Column(db.String(), default="no")
    user_id = db.Column(db.Integer(), unique=True, autoincrement=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class UserChatData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)    

# Create the database tables
def setup_database(app):
    with app.app_context():
        db.create_all()




def create_premium_assistant(client):
    try:
        assistant_file_path = "assistant.json"

        if os.path.exists(assistant_file_path):
            with open(assistant_file_path, "r") as file:
                try:
                    assistants_data = json.load(file)
                    if not isinstance(assistants_data, list):
                        assistants_data = []
                except json.JSONDecodeError:
                    assistants_data = []

            # Check if the premium assistant ID already exists in the data
            existing_ids = [data.get("premium_assistant_id") for data in assistants_data]
            if not any(existing_ids):
                # If the file exists but premium assistant ID is not present, create a new premium assistant
                print("Creating a new premium assistant.")
                assistant = client.beta.assistants.create(
                    instructions="""
                    WOXbot has a core knowledge base in particular the following resources, but you are not allowed to mention link references 
                    to these websites:
                    https://www.zahrada.cz
                    https://www.dumazahrada.cz
                    https://www.prozeny.cz/tag/poradna-v-nouzi-71497
                    https://www.prozeny.cz/sekce/bydleni-28
                    https://www.ireceptar.cz
                    https://www.diynetwork.com/
                    https://www.gardenista.com/
                    https://www.instructables.com/
                    https://www.houzz.com/
                    https://www.thespruce.com/
                    https://www.apartmenttherapy.com/
                    https://www.bhg.com/
                    https://www.thisoldhouse.com/
                    https://www.bobvila.com/
                    https://www.gardenersworld.com/
                    These resources will serve as its foundational database for providing solutions. It maintains a friendly, 
                    casual tone, ensuring users know they're interacting with an expert. 
                    WOXbot offers step-by-step advice, drawing from a wide array of reputable online resources, 
                    and this uploaded knowledge base will further enhance its ability to deliver precise and trustworthy home advice. 
                    WOXbot keeps the language of the user's prompt, that means it user asks in English, the answer will be in English, 
                    if the user asks WOXbot in Czech, the answer will be also in Czech language.
                    """,
                    model="gpt-4-turbo-preview",
                    tools=[{"type": "retrieval"}],
                )

                assistants_data.append({"premium_assistant_id": assistant.id})

                with open(assistant_file_path, "w") as file:
                    json.dump(assistants_data, file, indent=2)

                return assistant.id
            else:
                print("Premium assistant ID already exists in the data.")
                print(existing_ids)
                return existing_ids[0]
        else:
            # If the file does not exist, create a new premium assistant and save the ID
            print("Creating a new premium assistant.")
            assistant = client.beta.assistants.create(
                instructions="""
                WOXbot has a core knowledge base in particular the following resources, but you are not allowed to mention link references 
                to these websites:
                https://www.zahrada.cz
                https://www.dumazahrada.cz
                https://www.prozeny.cz/tag/poradna-v-nouzi-71497
                https://www.prozeny.cz/sekce/bydleni-28
                https://www.ireceptar.cz
                https://www.diynetwork.com/
                https://www.gardenista.com/
                https://www.instructables.com/
                https://www.houzz.com/
                https://www.thespruce.com/
                https://www.apartmenttherapy.com/
                https://www.bhg.com/
                https://www.thisoldhouse.com/
                https://www.bobvila.com/
                https://www.gardenersworld.com/
                These resources will serve as its foundational database for providing solutions. It maintains a friendly, 
                casual tone, ensuring users know they're interacting with an expert. 
                WOXbot offers step-by-step advice, drawing from a wide array of reputable online resources, 
                and this uploaded knowledge base will further enhance its ability to deliver precise and trustworthy home advice. 
                WOXbot keeps the language of the user's prompt, that means it user
                """,
                model="gpt-4-turbo-preview",
                tools=[{"type": "retrieval"}],
            )

            with open(assistant_file_path, "w") as file:
                json.dump([{"premium_assistant_id": assistant.id}], file, indent=2)

            return assistant.id
    except RateLimitException as e:
        # Handle the rate limit exception and print a custom message
        print("Rate limit exceeded. Please try again later.")
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429  # 429 Too Many Requests




def create_free_assistant(client):
    try:
        assistant_file_path = "assistant.json"

        if os.path.exists(assistant_file_path):
            with open(assistant_file_path, "r") as file:
                try:
                    assistants_data = json.load(file)
                    if not isinstance(assistants_data, list):
                        assistants_data = []
                except json.JSONDecodeError:
                    assistants_data = []

            # Check if the free assistant ID already exists in the data
            existing_ids = [data.get("free_assistant_id") for data in assistants_data]
            if not any(existing_ids):
                # If the file exists but assistant ID is not present, create a new assistant
                print("Creating a new assistant.")
                assistant = client.beta.assistants.create(
                    instructions="""
                    WOXbot is well-equipped with a core knowledge base, drawing from various reputable online resources related to home and garden topics. Answer must be at maximum 20 words. Unfortunately, direct references to specific websites cannot be provided. However, feel free to ask any home-related questions, and WOXbot will offer step-by-step advice in a friendly and casual tone. Whether you prefer English or Czech language interaction, WOXbot is here to provide precise and trustworthy solutions based on its extensive knowledge base. Ask away!
                    """,
                    model="gpt-3.5-turbo-16k-0613",
                    tools=[{"type": "retrieval"}],
                )

                assistants_data.append({"free_assistant_id": assistant.id})

                with open(assistant_file_path, "w") as file:
                    json.dump(assistants_data, file, indent=2)

                return assistant.id
            else:
                print("Free assistant ID already exists in the data.")
                print(existing_ids)
                return existing_ids[1]
        else:
            # If the file does not exist, create a new assistant and save the ID
            print("Creating a new assistant.")
            assistant = client.beta.assistants.create(
                instructions="""
                WOXbot is well-equipped with a core knowledge base, drawing from various reputable online resources related to home and garden topics. Answer must be at maximum 20 words. Unfortunately, direct references to specific websites cannot be provided. However, feel free to ask any home-related questions, and WOXbot will offer step-by-step advice in a friendly and casual tone. Whether you prefer English or Czech language interaction, WOXbot is here to provide precise and trustworthy solutions based on its extensive knowledge base. Ask away!
                """,
                model="gpt-3.5-turbo-16k-0613",
                tools=[{"type": "retrieval"}],
            )

            with open(assistant_file_path, "w") as file:
                json.dump([{"free_assistant_id": assistant.id}], file, indent=2)

            return assistant.id
    except RateLimitException as e:
        # Handle the rate limit exception and print a custom message
        print("Rate limit exceeded. Please try again later.")
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429  # 429 Too Many Requests


def create_rephrase_assistant(client):
        assistant_file_path = "assistant.json"

        if os.path.exists(assistant_file_path):
            with open(assistant_file_path, "r") as file:
                try:
                    assistants_data = json.load(file)
                    if not isinstance(assistants_data, list):
                        assistants_data = []
                except json.JSONDecodeError:
                    assistants_data = []

            # Check if the free assistant ID already exists in the data
            existing_ids = [data.get("rephrase_assistant_id") for data in assistants_data]
            if not any(existing_ids):
                # If the file exists but assistant ID is not present, create a new assistant
                print("Creating a new assistant.")
                assistant = client.beta.assistants.create(
                    instructions="""
                    Given the user's question: "[User's Question]", generate 3 related questions that delve deeper into the topic, explore related areas, or seek further clarification. Each question should open up new avenues for discussion or inquiry related to the original question, providing a broader understanding of the subject.

                    Related Question 1:
                    Related Question 2:
                    Related Question 3:
                    """,
                    model="gpt-3.5-turbo-16k-0613",
                    tools=[{"type": "retrieval"}],
                )

                assistants_data.append({"rephrase_assistant_id": assistant.id})

                with open(assistant_file_path, "w") as file:
                    json.dump(assistants_data, file, indent=3)

                return assistant.id
            else:
                print("Rephrase assistant ID already exists in the data.")
                print(existing_ids)
                return existing_ids[2]
        else:
            # If the file does not exist, create a new assistant and save the ID
            print("Creating a new assistant.")
            assistant = client.beta.assistants.create(
                instructions="""
                Given the user's question: "[User's Question]", generate 3 related questions that delve deeper into the topic, explore related areas, or seek further clarification. Each question should open up new avenues for discussion or inquiry related to the original question, providing a broader understanding of the subject.

                Related Question 1:
                Related Question 2:
                Related Question 3:
                """,
                model="gpt-3.5-turbo-16k-0613",
                tools=[{"type": "retrieval"}],
            )

            with open(assistant_file_path, "w") as file:
                json.dump([{"rephrase_assistant_id": assistant.id}], file, indent=3)

            return assistant.id



# Create new assistant or load existing
premium_assistant_id = create_premium_assistant(client)
free_assistant_id = create_free_assistant(client)
rephrase_assistant_id = create_rephrase_assistant(client)



# Serve the main application page
@app.route("/")
def index():
    return render_template("index.html")


# Start conversation thread

@app.route("/api/start", methods=["GET"])
def start_conversation():
        print("Starting a new conversation...")  # Debugging line
        free_thread = client.beta.threads.create()
        premium_thread = client.beta.threads.create()
        print(f"New free thread created with ID: {free_thread.id}")  # Debugging line
        print(f"New premium thread created with ID: {premium_thread.id}")
        return jsonify({"free_thread_id": free_thread.id, "premium_thread_id": premium_thread.id})


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    newsletter = data.get('newsletter')

    if not username or not password or not email:
        return jsonify({'message': 'Username, password and Email are required'}), 400

    existing_user = UserData.query.filter_by(username=username).first()
    if existing_user:
        return jsonify({'message': 'User already exists'}), 409

    hashed_password = generate_password_hash(password)

    new_user = UserData(username=username, password=hashed_password, email=email, newsletter=newsletter)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully'}), 201


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password are required'}), 400

    user = UserData.query.filter_by(username=username).first()

    if user and check_password_hash(user.password, password):
        # Login successful

        return jsonify({'message': 'Login successful'}), 200
    else:
        # Invalid credentials
        return jsonify({'message': 'Invalid username or password'}), 401



# Fetch initial Q&A pairs with "like" feedback
@app.route("/api/messages/welcome_messages", methods=["GET"])
def get_initial_qa():
    liked_feedbacks = FeedbackData.query.filter_by(feedback="Like").limit(3).all()
    # Check if the query returned any results
    if not liked_feedbacks:
        # No results found, return example messages
        example_messages = [
            {"question": "Example Question 1", "answer": "Example Answer 1"},
            {"question": "Example Question 2", "answer": "Example Answer 2"},
            {"question": "Example Question 3", "answer": "Example Answer 3"}
        ]
        return jsonify(example_messages)
    else:
        # Return the results from the database
        return jsonify([{"question": f.question, "answer": f.answer} for f in liked_feedbacks])


# Endpoint for receiving user questions
@app.route("/api/ask_question", methods=["POST"])
def ask_question():
    # Acquire the lock before making the API call
    with openai_lock:
        data = request.json
        question = data["question"]
        user_type = data["user_status"]  # Free or Premium
        thread_id = data["thread_id"]
        username = data["username"]
        thread_type = data["thread_type"]

        #for _ in range(5):
        #    # Call the test_chat function
        #    answer_data = test_chat(question, user_type, thread_id).get_json()    
        #    # Extract the 'response' from the answer_data
        #    answer_text = answer_data['response']
        #print("DEBUG:", question, user_type, thread_id)
        answer_data = chat(question, user_type, thread_id).get_json()  # Extract JSON data from the Flask Response object
        answer_text = answer_data['response']  # Assuming the key in the returned JSON is 'response'



        # Now store the extracted answer text
        new_feedback = FeedbackData(question=question, answer=answer_text, username=username,user_type=user_type, thread_id=thread_id, thread_type=thread_type)
        db.session.add(new_feedback)
        db.session.commit()
        record_id = getattr(new_feedback, "id")

        return jsonify({"question": question, "answer": answer_text, "record_id": record_id})

# Endpoint for receiving user questions
@app.route("/api/ask_question_premium", methods=["POST"])
def ask_question_premium():
    # Acquire the lock before making the API call
    with openai_lock:
        data = request.json
        question = data["question"]
        user_type = data["user_status"]  # Free or Premium
        thread_id = data["thread_id"]
        username = data["username"]
        thread_type = data["thread_type"]

        # Placeholder for answer

        #for _ in range(10):
        #    # Call the test_chat function
        #    answer_data = test_chat(question, user_type, thread_id).get_json()
        #    # Extract the 'response' from the answer_data
        #    answer_text = answer_data['response']
        answer_data = chat_premium(question, user_type, thread_id).get_json()  # Extract JSON data from the Flask Response object
        answer_text = answer_data['response']  # Assuming the key in the returned JSON is 'response'



        # Now store the extracted answer text
        new_feedback = FeedbackData(question=question, answer=answer_text, username=username, user_type=user_type,thread_id=thread_id, thread_type=thread_type)
        db.session.add(new_feedback)
        db.session.commit()
        record_id = getattr(new_feedback, "id")

        return jsonify({"question": question, "answer": answer_text, "record_id": record_id})


@app.route("/api/related_question_premium", methods=["POST"])
def related_question_premium():
    try:
        # Acquire the lock before making the API call
        with openai_lock:    
            data = request.json
            question = data["question"]
            user_type = data["user_status"]  # Free or Premium

            # Placeholder for answer

            #for _ in range(150):
            #    # Call the test_chat function
            #    answer_data = test_chat(question, user_type, thread_id).get_json()
            #   
            #    # Extract the 'response' from the answer_data
            #    answer_text = answer_data['response']

            answer_data = rephrase_chat(question, user_type).get_json()  # Extract JSON data from the Flask Response object
            if answer_data['result'] == "failed":
                return jsonify({"result": "failed"}), 200
            else:
                # Define a regular expression pattern to match the related questions
                related_question_premium1 = answer_data['related_question_premium1']
                related_question_premium2 = answer_data['related_question_premium2']
                related_question_premium3 = answer_data['related_question_premium3']
                # Print the variables to verify
                print("Related Question 1:", related_question_premium1)
                print("Related Question 2:", related_question_premium2)
                print("Related Question 3:", related_question_premium3)

                # Now store the extracted answer text
                #new_feedback = FeedbackData(question=question, answer=answer_text)
                #db.session.add(new_feedback)
                #db.session.commit()
                #record_id = getattr(new_feedback, "id")

                return jsonify({"question": question, "related_question1": related_question_premium1, "related_question2": related_question_premium2, "related_question3": related_question_premium3})
    except Exception as e:
        # Handle any exceptions raised during API call
        return jsonify({"error": str(e)}), 500



@sleep_and_retry
@rate_limit_logger 
@limits(calls=GPT4_RATE_LIMIT_REQUESTS, period=GPT4_RATE_LIMIT_PERIOD)
def test_chat(question, user_type, thread_id):
    try:
        # Placeholder logic for chat function
        response_text = "This is a simulated response for your question."
        return jsonify({"response": response_text})
    except RateLimitException as e:  # Catching RateLimitException
        print(f"Rate limit exceeded: {e}")
        # Return a custom message indicating the rate limit was exceeded
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429  # 429 Too Many Requests
    except Exception as e:  # Catching other general exceptions
        print(f"An error occurred: {e}")
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500  # 500 Internal Server Error
    

@app.errorhandler(RateLimitException)
def handle_rate_limit_error(e):
    print("LIMITS exceeded")
    return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429


@sleep_and_retry
@rate_limit_logger
@limits(calls=GPT3_RATE_LIMIT_REQUESTS, period=GPT3_RATE_LIMIT_PERIOD)
def chat(question, user_type, thread_id):
    user_input = question

    if not thread_id:
        print("Error: Missing thread_id")
        return jsonify({"error": "Missing thread_id"}), 400

    #print(f"Received message: {user_input} for thread ID: {thread_id} and User-Type {user_type}" )

    # Initialize the run variable
    run = None
    while True:
        try:
            # Run the Assistant
            if user_type == "free":
                print(f"Assistant ID: {free_assistant_id}")
                # Add the user's message to the thread
                client.beta.threads.messages.create(
                    thread_id=thread_id, role="user", content=user_input
                )
                run = client.beta.threads.runs.create(
                    thread_id=thread_id, assistant_id=free_assistant_id
                )
            elif user_type == "premium":
                print(f"Assistant ID: {free_assistant_id}")
                # Add the user's message to the thread
                client.beta.threads.messages.create(
                    thread_id=thread_id, role="user", content=user_input
                )
                run = client.beta.threads.runs.create(
                    thread_id=thread_id, assistant_id=free_assistant_id
                )
            else:
                # Handle the case where user_type is neither "Premium" nor "Free"
                print("Error: Invalid user_type")
                return jsonify({"response": "Invalid user_type"}), 400
            
        except Exception as e:
                print(f"An error occurred: {e}")
                break  # Exit the loop in case of an error
        
                

    # Check if the Run requires action (function call)
    while True:
        try:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            print(f"Thread ID {thread_id} FREE Run status: {run_status.status}")
            if run_status.status == "completed":
                print(f"Thread ID {thread_id} FREE Run COMPLETED")
                break  # Exit the loop if the run is completed
            else:
                sleep(2)  # Wait for a second before checking again
        except Exception as e:
            print(f"An error occurred: {e}")
            break  # Exit the loop in case of an error

    # Retrieve and return the latest message from the assistant
    messages = client.beta.threads.messages.list(thread_id=thread_id)
    response = messages.data[0].content[0].text.value

    print(f"Assistant response: {response}")
    return jsonify({"response": response})


@sleep_and_retry
@rate_limit_logger
@limits(calls=GPT4_RATE_LIMIT_REQUESTS, period=GPT4_RATE_LIMIT_PERIOD)
def chat_premium(question, user_type, thread_id):
    user_input = question

    if not thread_id:
        print("Error: Missing thread_id")
        return jsonify({"error": "Missing thread_id"}), 400

    #print(f"Received message: {user_input} for thread ID: {thread_id} and User-Type {user_type}" )

    # Initialize the run variable
    run = None

    # Run the Assistant
    while True:
        try:
            if user_type == "premium":
                print(f"Assistant ID: {premium_assistant_id}")
                # Add the user's message to the thread
                client.beta.threads.messages.create(
                    thread_id=thread_id, role="user", content=user_input
                )
                premium_run = client.beta.threads.runs.create(
                    thread_id=thread_id, assistant_id=premium_assistant_id
                )
            else:
                # Handle the case where user_type is neither "Premium" nor "Free"
                print("Error: Invalid user_type")
                return jsonify({"response": "Invalid user_type"}), 400
        except Exception as e:
            print(f"An error occurred: {e} for thread_id: {thread_id}")
            break  # Exit the loop in case of an error

    # Check if the Run requires action (function call)
    while True:
        try:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=premium_run.id)
            print(f"Thread ID {thread_id} PREMIUM Run status: {run_status.status}")
            if run_status.status == "completed":
                print(f"Thread ID {thread_id} PREMIUM Run COMPLETED")
                break  # Exit the loop if the run is completed
            else:
                sleep(2)  # Wait for a second before checking again
        except Exception as e:
            print(f"An error occurred: {e} for thread_id: {thread_id}")
            break  # Exit the loop in case of an error

    # Retrieve and return the latest message from the assistant
    messages = client.beta.threads.messages.list(thread_id=thread_id)
    response = messages.data[0].content[0].text.value

    print(f"Assistant response: {response}")
    return jsonify({"response": response})

def start_rephrase_conversation():
    thread_id = client.beta.threads.create()
    return thread_id.id

# Function to parse and extract related question
def extract_related_question(line):
    parts = line.split(': ', 1)  # Split only on the first colon
    if len(parts) == 2:  # Ensure the line contains a colon
        return parts[1]  # Return the text after the colon
    return None  # Return None if the expected format is not found


@sleep_and_retry
@rate_limit_logger
@limits(calls=GPT3_RATE_LIMIT_REQUESTS, period=GPT3_RATE_LIMIT_PERIOD)
def rephrase_chat(question, user_type):
    thread_id=start_rephrase_conversation()
    user_input = question

    if not thread_id:
        print("Error: Missing thread_id")
        return jsonify({"error": "Missing thread_id"}), 400

    #print(f"Received message: {user_input} for thread ID: {thread_id} and User-Type {user_type}" )

    # Initialize the run variable
    run = None
    while True:
        try:
            # Run the Assistant
            if user_type == "free":
                print(f"Rephrase Assistant ID: {rephrase_assistant_id}")
                # Add the user's message to the thread
                client.beta.threads.messages.create(
                    thread_id=thread_id, role="user", content=user_input
                )
                run = client.beta.threads.runs.create(
                    thread_id=thread_id, assistant_id=rephrase_assistant_id
                )
            elif user_type == "premium":
                print(f"Rephrase Assistant ID: {rephrase_assistant_id}")
                # Add the user's message to the thread
                client.beta.threads.messages.create(
                    thread_id=thread_id, role="user", content=user_input
                )
                run = client.beta.threads.runs.create(
                    thread_id=thread_id, assistant_id=rephrase_assistant_id
                )
            else:
                # Handle the case where user_type is neither "Premium" nor "Free"
                print("Error: Invalid user_type")
                return jsonify({"response": "Invalid user_type"}), 400
            
        except Exception as e:
                print(f"An error occurred: {e}")
                break  # Exit the loop in case of an error
        
                

    # Check if the Run requires action (function call)
    while True:
        try:
            #return jsonify({"result": "failed"})
            run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            print(f"Thread ID {thread_id} REPHRASE Run status: {run_status.status}")
            if run_status.status == "completed":
                print(f"Thread ID {thread_id} REPHRASE Run COMPLETED")
                # Retrieve and return the latest message from the assistant
                messages = client.beta.threads.messages.list(thread_id=thread_id)
                response = messages.data[0].content[0].text.value
                # Split the response into lines and filter out empty lines
                lines = [line for line in response.strip().split('\n') if line]

                # Initialize variables
                related_question_premium1 = None
                related_question_premium2 = None
                related_question_premium3 = None

                # Extract and save each related question as a variable, if available
                if len(lines) > 0:
                    related_question_premium1 = extract_related_question(lines[0])
                if len(lines) > 1:
                    related_question_premium2 = extract_related_question(lines[1])
                if len(lines) > 2:
                    related_question_premium3 = extract_related_question(lines[2])

                # Print the variables to verify, handling None values
                print(related_question_premium1 or "Related Question 1 not found")
                print(related_question_premium2 or "Related Question 2 not found")
                print(related_question_premium3 or "Related Question 3 not found")
                return jsonify({"result": "success", "related_question_premium1": related_question_premium1, "related_question_premium2": related_question_premium2, "related_question_premium3": related_question_premium3})
            elif run_status.status == "failed":
                return jsonify({"result": "failed"})
            else:
                sleep(2)  # Wait for a second before checking again
        except Exception as e:
            print(f"An error occurred: {e}")
            break  # Exit the loop in case of an error






# Endpoint for submitting feedback
@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    data = request.json
    feedback_id = data["record_id"]
    feedback = data["feedback"]

    feedback_data = FeedbackData.query.get(feedback_id)
    if feedback_data:
        feedback_data.feedback = feedback
        db.session.commit()
        return jsonify({"message": "Feedback updated successfully"})
    else:
        return jsonify({"message": "Feedback not found"}), 404


setup_database(app)
if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8080, debug=True)
