import json
import os
import random
import re
from hashlib import pbkdf2_hmac
from threading import Thread
from time import time
from math import ceil

import psycopg2
from bitstring import BitArray
from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

encoding = 'sha512'
iterations = 450959

def connect():
    conn = psycopg2.connect(
        dbname='postgres',
        user='postgres.pdkykbuvuioybyhbsibu',
        password=os.environ['DB_PASSWORD'],
        host=os.environ['DB_HOST'],
        port=6543
    )
    return conn

conn = connect()

battlepass_rewards = {
    "1": {"type": "booster", "count": 1},
    "2": {"type": "booster", "count": 1},
    "3": {"type": "avatar", "id": 3},
    "4": {"type": "booster", "count": 2},
    "5": {"type": "gems", "count": 100},
    "6": {"type": "booster", "count": 1},
    "7": {"type": "booster", "count": 3},
    "8": {"type": "gems", "count": 50},
    "9": {"type": "booster", "count": 1},
    "10": {"type": "skin", "id": 1},
    "11": {"type": "gems", "count": 100},
    "12": {"type": "booster", "count": 1},
    "13": {"type": "booster", "count": 2},
    "14": {"type": "avatar", "id": 2},
    "15": {"type": "gems", "count": 100},
    "16": {"type": "booster", "count": 2},
    "17": {"type": "gems", "count": 50},
    "18": {"type": "booster", "count": 1},
    "19": {"type": "booster", "count": 1},
    "20": {"type": "skin", "id": 4},
    "21": {"type": "gems", "count": 100},
    "22": {"type": "booster", "count": 2},
    "23": {"type": "booster", "count": 1},
    "24": {"type": "avatar", "id": 5},
    "25": {"type": "gems", "count": 100},
    "26": {"type": "booster", "count": 3},
    "27": {"type": "booster", "count": 1},
    "28": {"type": "gems", "count": 50},
    "29": {"type": "booster", "count": 1},
    "30": {"type": "skin", "id": 8},
    "31": {"type": "gems", "count": 100},
    "32": {"type": "booster", "count": 3},
    "33": {"type": "booster", "count": 2},
    "34": {"type": "avatar", "id": 8},
    "35": {"type": "gems", "count": 100},
    "36": {"type": "booster", "count": 3},
    "37": {"type": "gems", "count": 50},
    "38": {"type": "booster", "count": 1},
    "39": {"type": "gems", "count": 100},
    "40": {"type": "avatar", "id": 9},
} 


# FUNCTIONS
def create_game_board(size_x, size_y, mine_count):
    # Create empty board
    board = [0] * size_x * size_y

    # Place mines randomly on the board
    for _ in range(mine_count):
        while True:
            x, y = random.randint(0, size_x-1), random.randint(0, size_y-1)
            if board[x + y*size_x] != 9:
                board[x + y*size_x] = 9
                break

    # Update the counts around each mine
    for x in range(size_x):
        for y in range(size_y):
            if board[x + y*size_x] == 9:
                continue

            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size_x and 0 <= ny < size_y and board[nx + ny*size_x] == 9:
                        board[x + y*size_x] += 1
    return board

def sanitize_game_data(game_data):
    """Hide hidden tiles (-1) and only provide useful data (id: value)"""
    
    sanitized_data = {
        id: data['value'] if not data['hidden'] else -1
        for id, data in game_data['tiles'].items()
    }
    return sanitized_data

def uncover_all_tiles(game_data):
    """Ucover all hidden tiles (-1) and only provide useful data (id: value)"""

    sanitized_data = {
        id: data['value']
        for id, data in game_data['tiles'].items()
    }
    return sanitized_data

def uncover_tiles(tile_data, size_x, size_y, clicked_id):
    """Function uncovers all tiles that need to be uncovered (as per minesweeper rules)
    Tile provided MUST be a 0!"""
    process_queue = set()
    uncover_queue = set()
    tiles_processed = set()
    
    process_queue.add(str(clicked_id))
    uncover_queue.add(str(clicked_id))
    
    def queue_neighbors(tile_id):
        x, y = tile_id % size_x, tile_id // size_x
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
    
                nx, ny = x + dx, y + dy
                if 0 <= nx < size_x and 0 <= ny < size_y:
                    str_id = str(ny * size_x + nx)
                    if tile_data[str_id]['value'] == 0 and str_id not in tiles_processed:
                        process_queue.add(str_id)
                    uncover_queue.add(str_id)
        tiles_processed.add(str(tile_id))
    
    # Process tiles from queue, while also adding new tiles into the same queue
    while process_queue:
        current_id = process_queue.pop()
        queue_neighbors(int(current_id))
    
    # Uncover tiles from queue
    for tile in uncover_queue:
        tile_data[tile]['hidden'] = False
    return tile_data

def count_hidden_tiles(tile_data):
    return sum(1 for tile in tile_data.values() if tile['hidden'])

def calculate_xp(mine_count, size):
    if mine_count == 0:
        return 0
    mine_percentage = mine_count/size
    if mine_percentage < 0.1 or size < 100:
        return 0

    if mine_percentage >= 0.35 and size >= 2500:
        return 200
    
    difficulty_bonus_dict = {
        0.15: 25,
        0.2: 50,
        0.35: 75
    }
    for key, value in difficulty_bonus_dict.items():
        if mine_percentage < key:
            difficulty_bonus = value
            break
    else:
        difficulty_bonus = 100

    size_bonus_dict = {
        400: 0,
        900: 25,
        2500: 50
    }
    for key, value in size_bonus_dict.items():
        if size < key:
            size_bonus = value
            break
    else:    
        size_bonus = 75

    return difficulty_bonus + size_bonus

def get_battlepass_lvl(battlepass_xp):
    expRequired = 100
    expIncrementAmount = 25
    currentLevel = 0

    while battlepass_xp >= expRequired:
        battlepass_xp -= expRequired
        currentLevel += 1
        expRequired += expIncrementAmount
    return currentLevel


# ROUTES
@app.route('/')
def index():
    return "This is only an api! If you want to access the game, go to <a href=\"https://sapper-zeta.vercel.app/\">https://sapper-zeta.vercel.app/</a>"

@app.route('/health')
@cross_origin()
def health():
    start1 = time()
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "INSERT INTO test (value) VALUES (%s)"
        values = ('ABX',)
        cursor.execute(sql, values)
        timing1 = time()-start1
        
        start2 = time()
        sql = "SELECT value FROM test"
        cursor.execute(sql)
        row = cursor.fetchone()
        if row[0] == 'ABX':
            timing2 = time()-start2
            data = {
                'response': 'ok',
                'timing': f'{timing1}s | {timing2}s'
            }
            cursor.close()
            return jsonify(data), 200
        else:
            timing2 = time()-start2
            data = {
                "error": 'db error'
            }
            cursor.close()
            return jsonify(data), 500
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500

@app.route('/login', methods=['POST'])
@cross_origin()
def login():
    print("got login request!")
    # session_id = request.form['session_id']

    # if session_id:
        # return jsonify({"type":"fail", "reason": "user already logged in"}), 200
    
    email = request.form['email']
    password = request.form['password']
    if len(password) < 8 or len(password) > 64:
        print("invalid password")
        return jsonify({"type":"fail", "reason":"invalid password length"}), 200

    
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT uuid, password_hash, salt, username, xp, bp_xp, coins, gems \
        FROM users WHERE email = %s"
        values = (email,)
        cursor.execute(sql, values)
        user = cursor.fetchone()
        
        if user is None:
            cursor.close()
            return jsonify({
                "type":"fail", 
                "reason":"username or password is incorrect"
            }), 200
    
        uuid = user[0]
        db_hash = BitArray(bin=user[1]).bytes
        db_salt = BitArray(bin=user[2]).bytes
        username = user[3]
        xp = user[4]
        battlepass_xp = user[5]
        coins = user[6]
        gems = user[7]
        
        password_hash = pbkdf2_hmac(
            encoding, 
            password.encode('utf-8'), 
            db_salt, 
            iterations
        )
        
        if db_hash != password_hash:
            cursor.close()
            return jsonify({"type":"fail", "reason":"username or password is incorrect"}), 200
    
        sql = "with rows as (INSERT INTO sessions (user_id) VALUES (%s) RETURNING session_id) SELECT session_id FROM rows"
        values = (uuid, )
        cursor.execute(sql, values)
        conn.commit()
        session = cursor.fetchone()
        cursor.close()
    
        if not session:
            return jsonify({"error":"unknown db error"}), 500
    
        print(f"new session_id {session[0]} for user {email} with uuid {uuid}")
        return jsonify({
            "session_id": session[0], 
            "username": username,
            "xp": xp,
            "battlepass_xp": battlepass_xp,
            "coins": coins,
            "gems": gems,
            "type": "success"
        }), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500    

@app.route('/register', methods=['POST'])
@cross_origin()
def register():
    print("got register request!")
    # session_id = request.form['session_id']

    # if session_id:
        # return jsonify({"type":"fail", "reason": "user already logged in"}), 200
    
    email = request.form['email']
    
    username = request.form['username']
    if re.match(f"^[a-zA-Z0-9_]{5,24}$", username):
        print("invalid username")
        return jsonify({"type":"fail", "reason":"invalid username"}), 200
        
    password = request.form['password']
    if len(password) < 8 or len(password) > 64:
        print("invalid password")
        return jsonify({"type":"fail", "reason":"invalid password length"}), 200


    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT uuid FROM users WHERE email = %s"
        values = (email, )
        cursor.execute(sql, values)
        existing_email = cursor.fetchone()
        
        if existing_email:
            cursor.close()
            return jsonify({"type":"fail", "reason":"account with this email already exists"}), 200
            
        sql = "SELECT uuid FROM users WHERE username = %s"
        values = (username, )
        cursor.execute(sql, values)
        existing_username = cursor.fetchone()
    
        if existing_username:
            cursor.close()
            return jsonify({"type":"fail", "reason":"username is taken"}), 200
    
        salt = os.urandom(64)
        password_hash = pbkdf2_hmac(
            encoding, 
            password.encode('utf-8'), 
            salt, 
            iterations
        )
    
        sql = "INSERT INTO users (email, username, password_hash, salt) VALUES (%s, %s, right(%s::text, -1)::bit(512), right(%s::text, -1)::bit(512))"
        values = (email, username, password_hash, salt)
        cursor.execute(sql, values)
        sql = "SELECT uuid, email FROM users WHERE username = %s"
        values = (username, )
        cursor.execute(sql, values)
        conn.commit()
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({"error":"unknown db error"}), 500
        print(f"created account {user[0]} with email {user[1]}")
        
        sql = "with rows as (INSERT INTO sessions (user_id) VALUES (%s) RETURNING session_id) SELECT session_id FROM rows"
        values = (user[0], )
        cursor.execute(sql, values)
        session = cursor.fetchone()
        cursor.close()
    
        if not session:
            return jsonify({"error":"unknown db error"}), 500
    
        print(f"and session_id {session[0]}")
        return jsonify({
            "type": "success", 
            "session_id": session[0],
            "username": username
        }), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500

@app.route('/logout', methods=['POST'])
@cross_origin()
def logout():
    print("got logout request!")
    session_id = request.json['session_id']

    if not session_id:
        print("user already logged out")
        return jsonify({"type":"success"}), 200
    
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "DELETE FROM sessions WHERE session_id = %s"
        values = (session_id, )
        cursor.execute(sql, values)
        conn.commit()
    
        print(f"Logged out user with session_id {session_id}")
        cursor.close()
        return jsonify({"type":"success"}), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500

@app.route('/change_password', methods=['POST'])
@cross_origin()
def change_password():
    session_id = request.form['session_id']
    if not session_id:
        return jsonify({
            "type":"fail", 
            "reason": "missing session id"
        }), 400
    
    old_password = request.form['old_password']
    if len(old_password) < 8 or len(old_password) > 64:
        return jsonify({
            "type":"fail", 
            "reason":"invalid password length"
        }), 400

    new_password = request.form['new_password']
    if len(new_password) < 8 or len(new_password) > 64:
        return jsonify({
            "type":"fail", 
            "reason":"invalid password length"
        }), 400

    confirm_new_password = request.form['confirm_new_password']
    if confirm_new_password != new_password:
        return jsonify({
            "type":"fail", 
            "reason":"passwords do not match"
        }), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s FOR UPDATE"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        user_id = session[0]
        sql = "SELECT password_hash, salt FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
    
        if not user:
            cursor.close()
            return jsonify({"error":"unknown db error"}), 500
    
        db_hash = BitArray(bin=user[0]).bytes
        db_salt = BitArray(bin=user[1]).bytes
        
        old_password_hash = pbkdf2_hmac(
            encoding, 
            old_password.encode('utf-8'), 
            db_salt, 
            iterations
        )
        
        if db_hash != old_password_hash:
            cursor.close()
            return jsonify({"type":"fail", "reason":"old password is incorrect"}), 401

        # Password is correct. Now change the password
        new_salt = os.urandom(64)
        new_password_hash = pbkdf2_hmac(
            encoding, 
            new_password.encode('utf-8'), 
            new_salt, 
            iterations
        )
    
        # Update password and hash in db
        sql = "UPDATE users SET \
                 password_hash = right(%s::text, -1)::bit(512), \
                 salt = right(%s::text, -1)::bit(512) \
               WHERE uuid = %s"
        values = (new_password_hash, new_salt, user_id)
        cursor.execute(sql, values)
        
        # Delete all existing sessions for user
        sql = "DELETE FROM sessions WHERE user_id = %s"
        values = (user_id, )
        cursor.execute(sql, values)

        # Add a new session (renew old one)
        sql = "WITH rows AS (INSERT INTO sessions (user_id) VALUES (%s) RETURNING session_id) SELECT session_id FROM rows"
        values = (user_id, )
        cursor.execute(sql, values)
        conn.commit()
        session = cursor.fetchone()
        cursor.close()

        if not session:
            return jsonify({"error":"unknown db error"}), 500
    
        return jsonify({
            "type": "success", 
            "session_id": session[0]
        }), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500

@app.route('/get_user_id')
@cross_origin()
def get_user_id():
    session_id = request.json['session_id']
    if not session_id:
        return jsonify({"type": "fail", "reason": "missing session id"}), 401
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        return jsonify({
            "type": "success",
            "id": session[0]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_statistics', methods=['POST'])
@cross_origin()
def get_statistics():
    session_id = request.json['session_id']
    
    if not session_id:
        return jsonify({"type": "fail", "reason": "missing session id"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT username, avatar, xp, statistics FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "user doesn't exist"}), 400
        
        return jsonify({
            "type": "success",
            "username": user[0],
            "avatar": user[1],
            "xp": user[2],
            "statistics": json.loads(user[3])
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# FRIEND ENDPOINTS
@app.route('/add_friend', methods=['POST'])
@cross_origin()
def add_friend():
    session_id = request.json['session_id']
    friend_id = request.json['user_id']

    if not session_id or not friend_id:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        user_id = session[0]

        # Check if friend exists
        sql = "SELECT uuid FROM users WHERE uuid = %s"
        values = (friend_id,)
        cursor.execute(sql, values)
        friend = cursor.fetchone()

        if not friend or not friend[0]:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "friend does not exist"
            }), 400

        # Get user's friend list
        sql = "SELECT friends FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id,)
        cursor.execute(sql, values)
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({
                "error": "failed to fetch user from database"
            }), 500

        str_friends_list = user[0].strip("\{\}")
        friends_list = str_friends_list.split(',')
        if friend_id in friends_list:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "user is already your friend"
            }), 400


        # Add friend to user's friend list
        if friends_list[0]:
            friends_list.append(friend_id)
        else:
            friends_list = [friend_id]

        sql = "UPDATE users SET friends = %s::uuid[] WHERE uuid = %s"
        values = (friends_list, user_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()

        return jsonify({"type": "success"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/remove_friend', methods=['POST'])
@cross_origin()
def remove_friend():
    session_id = request.json['session_id']
    friend_id = request.json['user_id']

    if not session_id or not friend_id:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        user_id = session[0]

        # Get user's friend list
        sql = "SELECT friends FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id,)
        cursor.execute(sql, values)
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"error": "unknown db error"}), 500

        str_friends_list = user[0].strip("\{\}")
        friends_list = str_friends_list.split(',')
        if friend_id not in friends_list:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "user is not your friend"
            }), 400


        # Remove friend from user's friend list
        if friends_list[0]:
            friends_list.remove(friend_id)
        else:
            friends_list = []

        sql = "UPDATE users SET friends = %s::uuid[] WHERE uuid = %s"
        values = (friends_list, user_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()

        return jsonify({"type": "success"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_friends', methods=['POST'])
@cross_origin()
def get_friends():
    session_id = request.json['session_id']

    if not session_id:
        return jsonify({"type": "fail", "reason": "missing session id"}), 400
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        user_id = session[0]

        # Get user's friend list
        sql = "SELECT friends FROM users WHERE uuid = %s"
        values = (user_id,)
        cursor.execute(sql, values)
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"error": "unknown db error"}), 500

        # Convert string array to a string like this: "'val1','val2','val3'"
        str_friends_list = str(user[0].strip("\{\}").split(',')).strip("[]")

        if str_friends_list == "''":
            return jsonify({
                "type": "success",
                "friends": []
            }), 200

        sql = f"SELECT uuid, username, avatar FROM users WHERE uuid IN ({str_friends_list})"
        cursor.execute(sql)
        friends = cursor.fetchall()
        cursor.close()

        data = []
        for friend in friends:
            data.append({
                "id": friend[0],
                "username": friend[1],
                "avatar": friend[2]
            })

        return jsonify({
            "type": "success",
            "friends": data
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search_users', methods=['POST'])
@cross_origin()
def search_users():
    session_id = request.json['session_id']
    query = request.json['query']

    if not session_id or not query:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "wrong session id"
            }), 401

        user_id = session[0]

        sql = "SELECT uuid, username, avatar FROM users WHERE username ~* %s AND uuid != %s::uuid"
        values = (query, user_id)
        cursor.execute(sql, values)
        friends = cursor.fetchall()
        cursor.close()

        data = []
        for friend in friends:
            data.append({
                "id": friend[0],
                "username": friend[1],
                "avatar": friend[2]
            })

        return jsonify({
            "type": "success",
            "users": data
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/user_info', methods=['POST'])
@cross_origin()
def user_info():
    session_id = request.json['session_id']
    friend_id = request.json['user_id']
    
    if not session_id or not friend_id:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        sql = "SELECT username, avatar, xp, statistics FROM users WHERE uuid = %s"
        values = (friend_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "user doesn't exist"}), 400
        
        return jsonify({
            "type": "success",
            "username": user[0],
            "avatar": user[1],
            "xp": user[2],
            "statistics": json.loads(user[3])
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# SHOP ENDPOINTS
# general
@app.route('/get_balance', methods=['POST'])
@cross_origin()
def get_balance():
    session_id = request.json['session_id']

    if not session_id:
        return jsonify({"type": "fail", "reason": "missing session id"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT coins, gems FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "wrong user id"}), 401
        
        return jsonify({
            "type": "success",
            "coins": user[0],
            "gems": user[1]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_xp', methods=['POST'])
@cross_origin()
def get_xp():
    session_id = request.json['session_id']

    if not session_id:
        return jsonify({"type": "fail", "reason": "missing session id"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT xp, bp_xp FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "wrong user id"}), 404
        
        return jsonify({
            "type": "success",
            "xp": user[0],
            "battlepass_xp": user[1]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# skins
@app.route('/get_all_skins')
@cross_origin()
def get_all_skins():
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT * FROM skins"
        cursor.execute(sql)
        skins = cursor.fetchall()
        cursor.close()
        
        data = {}
        for skin in skins:
            skin_id = skin[0]
            skin_name = skin[1]
            price_coins = skin[2]
            price_gems = skin[3]
            
            data[str(skin_id)] = {
                'name': skin_name,
                'price_coins': price_coins,
                'price_gems': price_gems
            }
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_user_skins', methods=['POST'])
@cross_origin()
def get_user_skins():
    session_id = request.json['session_id']
    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT owned_skins FROM users WHERE uuid = %s"
        values = (user_id,)
        cursor.execute(sql, values)
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong user id"}), 401
        
        user_skins = user[0]
        return jsonify({"ids": user_skins}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/buy_skin', methods=['POST'])
@cross_origin()
def buy_skin():
    session_id = request.json['session_id']
    skin_id = request.json['skin_id']
    currency = request.json['currency']

    if not session_id or not skin_id or not currency:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400

    if currency not in ['coins', 'gems']:
        return jsonify({"type": "fail", "reason": "invalid currency"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = f"SELECT {currency}, owned_skins FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id,)
        cursor.execute(sql, values)
        user = cursor.fetchone()

        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong user id"}), 401

        user_balance = user[0]
        user_skins = user[1] if user[1] else []

        if skin_id in user_skins:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "skin already owned"
            }), 400

        sql = f"SELECT price_{currency} FROM skins WHERE sid = %s"
        values = (skin_id, )
        cursor.execute(sql, values)
        skin = cursor.fetchone()

        if not skin:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong skin id"}), 401

        skin_price = skin[0]

        if skin_price > user_balance:
            cursor.close()
            return jsonify({"type": "fail", "reason": "insufficient funds"}), 401

        user_skins.append(skin_id)
        sql = f"UPDATE users SET {currency} = {currency} - %s, owned_skins = %s WHERE uuid = %s"
        values = (skin_price, user_skins, user_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()

        return jsonify({
            "type": "success",
            "currency": currency,
            "new_balance": user_balance - skin_price
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# currency
@app.route('/buy_gems', methods=['POST'])
@cross_origin()
def buy_gems():
    session_id = request.json['session_id']
    amount = request.json['gemsQuantity']

    if not session_id or not amount:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "WITH rows AS \
               (UPDATE users SET gems = gems + %s WHERE uuid = %s RETURNING gems) \
               SELECT gems FROM rows"
        values = (amount, user_id)
        cursor.execute(sql, values)
        conn.commit()
        gems = cursor.fetchone()[0]
        cursor.close()

        return jsonify({
            "type": "success",
            "new_balance": gems
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# battlepass
@app.route('/buy_battlepass', methods=['POST'])
@cross_origin()
def buy_battlepass():
    session_id = request.json['session_id']
    battlepass_cost = 950

    if not session_id:
        return jsonify({"type": "fail", "reason": "not logged in"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT gems FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        gems = user[0]
        if gems < battlepass_cost:
            cursor.close()
            return jsonify({"type": "fail", "reason": "not enough gems"}), 401

        sql = "UPDATE users SET gems = gems - %s, owns_battlepass = %s WHERE uuid = %s"
        values = (battlepass_cost, True, user_id)
        cursor.execute(sql, values)
        conn.commit()

        # Add items from battlepass
        sql = "SELECT gems, bp_xp, booster_count, owned_avatars, owned_skins \
               FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()

        gems = user[0]
        battlepass_xp = user[1]
        booster_count = user[2]
        owned_avatars = user[3]
        owned_skins = user[4]

        battlepass_lvl = get_battlepass_lvl(battlepass_xp)
        for tier in range(1, battlepass_lvl+1):
            item = battlepass_rewards[str(tier)]
            if item['type'] == "booster":
                booster_count += item['count']
                continue
            if item['type'] == "avatar":
                owned_avatars.append(item['id'])
                continue
            if item['type'] == "skin":
                owned_skins.append(item['id'])
                continue
        
        sql = "UPDATE users \
               SET booster_count = %s, owned_avatars = %s, owned_skins = %s \
               WHERE uuid = %s"
        values = (booster_count, owned_avatars, owned_skins, user_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()

        return jsonify({
            "type": "success",
            "new_balance": gems
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/battlepass_status', methods=['POST'])
@cross_origin()
def battlepass_status():
    session_id = request.json['session_id']

    if not session_id:
        return jsonify({"type": "fail", "reason": "not logged in"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT owns_battlepass FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        owns_battlepass = "true" if user[0] else "false"
        return jsonify({
            "type": "success",
            "owned": owns_battlepass
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# boosters
@app.route('/get_booster_count', methods=['POST'])
@cross_origin()
def get_booster_count():
    session_id = request.json['session_id']
    
    if not session_id:
        return jsonify({"type": "fail", "reason": "not logged in"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT booster_count FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        booster_count = user[0]
        return jsonify({
            "type": "success",
            "booster_count": booster_count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/buy_booster', methods=['POST'])
@cross_origin()
def buy_booster():
    session_id = request.json['session_id']
    currency = request.json['currency']
    
    if not session_id or not currency:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400
    
    if currency == "coins":
        booster_cost = 200
    elif currency == "gems":
        booster_cost = 50
    else:
        return jsonify({"type": "fail", "reason": "wrong currency"}), 400


    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = f"SELECT {currency} FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        balance = user[0]
        if balance < booster_cost:
            cursor.close()
            return jsonify({"type": "fail", "reason": f"not enough {currency}"}), 401

        sql = f"WITH rows AS \
                (UPDATE users SET {currency} = {currency} - %s, booster_count = booster_count + %s WHERE uuid = %s RETURNING booster_count)\
                SELECT booster_count FROM rows"
        values = (booster_cost, 1, user_id)
        cursor.execute(sql, values)
        conn.commit()

        booster_count = cursor.fetchone()[0]
        balance -= booster_cost

        cursor.close()

        return jsonify({
            "type": "success",
            "new_balance": balance,
            "currency": currency,
            "booster_count": booster_count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# avatars
@app.route('/set_avatar', methods=['POST'])
@cross_origin()
def set_avatar():
    session_id = request.json['session_id']
    avatar_id = request.json['avatar_id']
    
    if not session_id or not avatar_id:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = f"SELECT owned_avatars FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        owned_avatars = list(user[0])
        if avatar_id not in owned_avatars:
            cursor.close()
            return jsonify({"type": "fail", "reason": f"user doesn't own avatar with id {avatar_id}"}), 401

        sql = f"UPDATE users SET avatar = %s WHERE uuid = %s"
        values = (avatar_id, user_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()

        return jsonify({"type": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_avatar', methods=['POST'])
@cross_origin()
def get_avatar():
    session_id = request.json['session_id']
    
    if not session_id:
        return jsonify({"type": "fail", "reason": "not logged in"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = f"SELECT avatar FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        avatar_id = user[0]
        return jsonify({
            "type": "success",
            "avatar_id": avatar_id
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_user_avatars', methods=['POST'])
@cross_origin()
def get_user_avatars():
    session_id = request.json['session_id']
    
    if not session_id:
        return jsonify({"type": "fail", "reason": "not logged in"}), 400

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()

        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = f"SELECT owned_avatars FROM users WHERE uuid = %s"
        values = (user_id, )
        cursor.execute(sql, values)
        user = cursor.fetchone()
        cursor.close()

        if not user:
            return jsonify({"type": "fail", "reason": "unknown user error"}), 400
        
        owned_avatars = user[0]
        return jsonify({
            "type": "success",
            "owned_avatars": owned_avatars
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# GAME ENDPOINTS
@app.route('/click_tile', methods=['POST'])
@cross_origin()
def click_tile():
    session_id = request.json['session_id']
    tile_id = request.json['tile_id']

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        session = cursor.fetchone()
    
        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401

        user_id = session[0]
        sql = "SELECT statistics FROM users WHERE uuid = %s FOR UPDATE"
        values = (user_id,)
        cursor.execute(sql, values)
        user_stats = cursor.fetchone()

        if not user_stats:
            cursor.close()
            return jsonify({"error": "unknown db error"}), 500

        statistics = json.loads(user_stats[0])
        statistics['tiles_clicked'] += 1
        
        sql = "SELECT data, extract(epoch from start_time)::integer FROM games WHERE game_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        game = cursor.fetchone()
    
        if not game:
            return jsonify({"type": "fail", "reason": "game not found"}), 404

        def delete_game_from_database(session_id):
            print(f"Deleting game from database for session {session_id}")
            cursor = conn.cursor()
            sql = "DELETE FROM games WHERE game_id = %s"
            values = (session_id,)
            cursor.execute(sql, values)
            conn.commit()
            cursor.close()
            return
        
        game_data = json.loads(game[0])
        timer_started = game_data['timer_started']
        start_time = game[1] if timer_started else -1
        if not timer_started:
            game_data['timer_started'] = True
            timer_started = True
            sql = "UPDATE games SET data = %s, start_time = NOW() WHERE game_id = %s"
            values = (json.dumps(game_data), session_id)
            cursor.execute(sql, values)
            conn.commit()
        
        tiles = game_data['tiles']
        
        # id not found
        if tile_id not in tiles:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "tile not found",
                "board": sanitize_game_data(game_data)
            }), 404

        # Already clicked (not hidden)
        if not tiles[tile_id]['hidden']:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "tile already clicked",
                "board": sanitize_game_data(game_data)
            }), 400

        # Loss condition
        if tiles[tile_id]['value'] == 9:
            # Add statistics
            statistics['games_played'] += 1
            miliseconds_played = int((time() - start_time)*100) if start_time != -1 else -1
            statistics['miliseconds_played'] += miliseconds_played

            sql = "UPDATE users SET statistics = %s WHERE uuid = %s"
            values = (json.dumps(statistics), user_id)
            cursor.execute(sql, values)
            conn.commit()

            # Delete game from database in another thread
            thread = Thread(
                target=delete_game_from_database, 
                kwargs={'session_id': session_id}
            )
            thread.start()

            tiles[tile_id]['value'] = 10 # Blow up mine visually
            tiles[tile_id]['hidden'] = False
            game_data['tiles'] = tiles
            return jsonify({
                "type": "loss", 
                "board": uncover_all_tiles(game_data),
                "miliseconds_played": miliseconds_played
            }), 200

        # Uncover tiles, because a number tile got clicked
        if tiles[tile_id]['value'] in range(1, 9):
            tiles[tile_id]['hidden'] = False
        elif tiles[tile_id]['value'] == 0:
            tiles = uncover_tiles(tiles, game_data['size_x'], game_data['size_y'], tile_id)
        else:
            cursor.close()
            return jsonify({
                "type": "fail", 
                "reason": "unknown tile value",
                "board": sanitize_game_data(game_data)
            }), 400

        game_data['tiles'] = tiles
        
        # Win condition
        if count_hidden_tiles(tiles) == game_data['mine_count']:
            sql = "SELECT owns_battlepass, statistics FROM users WHERE uuid = %s FOR UPDATE"
            values = (user_id, )
            cursor.execute(sql, values)
            user = cursor.fetchone()

            if not user:
                cursor.close()
                return jsonify({"error": "unknown db error"}), 500
            
            # Add statistics
            statistics['games_won'] += 1
            statistics['games_played'] += 1
            miliseconds_played = int((time() - start_time)*100) if start_time != -1 else -1
            statistics['miliseconds_played'] += miliseconds_played

            # If battlepass active, add multiplier
            bp_multiplier = 0
            owns_battlepass = user[0]
            if owns_battlepass:
                bp_multiplier = 0.25

            # If booster active, add multiplier
            boost_multiplier = 0
            if game_data['booster_active']:
                boost_multiplier = 0.25

            # Calculate XP
            base_xp = calculate_xp(
                game_data['mine_count'], 
                game_data['size_x'] * game_data['size_y']
            )

            added_coins = int(base_xp * (1 + boost_multiplier))
            added_xp = int(base_xp * (1 + boost_multiplier))
            added_battlepass_xp = int(base_xp * (1 + boost_multiplier + bp_multiplier))

            # Add XP, Battlepass XP and coins
            sql = "WITH row AS ( \
                     UPDATE users \
                     SET coins = coins+%s, xp = xp+%s, bp_xp = bp_xp+%s, statistics = %s \
                     WHERE uuid = %s \
                     RETURNING xp, bp_xp, coins \
                   ) SELECT xp, bp_xp, coins FROM row"
            values = (added_coins, added_xp, added_battlepass_xp, json.dumps(statistics), user_id)
            cursor.execute(sql, values)
            conn.commit()
            user = cursor.fetchone()

            user_xp = user[0]
            user_battlepass_xp = user[1]
            user_coins = user[2]

            # If battlepass lvl changed, give rewards
            old_battlepass_lvl = get_battlepass_lvl(user_battlepass_xp - added_battlepass_xp)
            new_battlepass_lvl = get_battlepass_lvl(user_battlepass_xp)
            bp_reward = "false"
            if new_battlepass_lvl > old_battlepass_lvl:
                bp_reward = "true"
                if owns_battlepass:
                    sql = "SELECT booster_count, owned_avatars, owned_skins \
                        FROM users WHERE uuid = %s FOR UPDATE"
                    values = (user_id, )
                    cursor.execute(sql, values)
                    user = cursor.fetchone()

                    booster_count = user[0]
                    owned_avatars = user[1]
                    owned_skins = user[2]

                    for tier in range(max(old_battlepass_lvl, 1), new_battlepass_lvl+1):
                        item = battlepass_rewards[str(tier)]
                        if item['type'] == "booster":
                            booster_count += item['count']
                            continue
                        if item['type'] == "avatar":
                            owned_avatars.append(item['id'])
                            continue
                        if item['type'] == "skin":
                            owned_skins.append(item['id'])
                            continue
                    
                    sql = "UPDATE users \
                        SET booster_count = %s, owned_avatars = %s, owned_skins = %s \
                        WHERE uuid = %s"
                    values = (booster_count, owned_avatars, owned_skins, user_id)
                    cursor.execute(sql, values)
                    conn.commit()

            cursor.close()

            # Delete game from database in another thread
            thread = Thread(
                target=delete_game_from_database, 
                kwargs={'session_id': session_id}
            )
            thread.start()

            board = sanitize_game_data(game_data)
            result = jsonify({
                "type": "win", 
                "board": board,
                "xp": user_xp,
                "added_xp": added_xp,
                "coins": user_coins,
                "added_coins": added_coins,
                "battlepass_xp": user_battlepass_xp,
                "added_battlepass_xp": added_battlepass_xp,
                "battlepass_reward": bp_reward,
                "miliseconds_played": miliseconds_played
            })
            return result, 200

        # Update statistics
        sql = "UPDATE users SET statistics = %s WHERE uuid = %s"
        values = (json.dumps(statistics), user_id)
        cursor.execute(sql, values)
        conn.commit()

        # Update game state in database
        sql = "UPDATE games SET data = %s WHERE game_id = %s"
        values = (json.dumps(game_data), session_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        
        result = {
            "type": "playing",
            "board": sanitize_game_data(game_data)
        }
        if start_time:
            result['start_time'] = start_time
        return jsonify(result), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500

@app.route('/create_game', methods=['POST'])
@cross_origin()
def create_game():
    # [session_id, size_x, size_y, mine_count, booster_used]
    session_id = request.json['session_id']
    size_x = request.json['size_x']
    size_y = request.json['size_y']
    difficulty = str(request.json['difficulty'])
    booster_used = request.json['booster_used']

    if not session_id or not size_x or not size_y or not difficulty or booster_used is None:
        return jsonify({"type": "fail", "reason": "missing parameters"}), 400

    booster_used = bool(int(booster_used) == 1)
    difficulty_list = {
        '1': 0.1,
        '2': 0.15,
        '3': 0.2,
        '4': 0.35
    }
    mine_count = ceil(difficulty_list[difficulty] * size_x * size_y)

    try:
        cursor = conn.cursor()
    except:
        conn = connect()
        cursor = conn.cursor()
    try:
        sql = "SELECT user_id FROM sessions WHERE session_id = %s"
        values = (session_id, )
        cursor.execute(sql, values)
        session = cursor.fetchone()
    
        if not session:
            cursor.close()
            return jsonify({"type": "fail", "reason": "wrong session id"}), 401
    
        user_id = session[0]

        sql = "SELECT data FROM games WHERE game_id = %s"
        values = (session_id, )
        cursor.execute(sql, values)
        game = cursor.fetchone()
    
        # Delete old game if left in database
        if game:
            sql = "DELETE FROM games WHERE game_id = %s"
            values = (session_id, )
            cursor.execute(sql, values)
            conn.commit()
            print(f"deleted old game for session {session_id}")
    
        # Remove booster from user if used
        if booster_used:
            sql = "SELECT booster_count FROM users WHERE uuid = %s"
            values = (user_id, )
            cursor.execute(sql, values)
            user = cursor.fetchone()

            if not user:
                cursor.close()
                return jsonify({"type": "fail", "reason": "wrong user id"}), 401

            booster_count = user[0]
            if booster_count < 1:
                cursor.close()
                return jsonify({"type": "fail", "reason": "insufficient amount of boosters"}), 401

            sql = "UPDATE users SET booster_count = %s WHERE uuid = %s"
            values = (booster_count-1, user_id)
            cursor.execute(sql, values)
            conn.commit()

        # Creating game data
        game_board = create_game_board(size_x, size_y, mine_count)
        game_data = {
            'tiles': {
                id: {'value': value, 'hidden': True} 
                for id, value in enumerate(game_board)
            },
            'size_x': size_x,
            'size_y': size_y,
            'mine_count': mine_count,
            'timer_started': False,
            'booster_active': booster_used
        }
        sql = "INSERT INTO games (game_id, data) VALUES (%s, %s)"
        values = (session_id, json.dumps(game_data))
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        
        return jsonify({"type": "success"}), 200
    except Exception as e:
        cursor.close()
        return jsonify({"error": str(e)}), 500
