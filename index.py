import json
import os
import random
import re
from hashlib import pbkdf2_hmac
from threading import Thread
from time import time

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
        user='postgres',
        password=os.environ['DB_PASSWORD'],
        host=os.environ['DB_HOST'],
        port=5432
    )
    return conn

conn = connect()

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

def uncover_all_mines(game_data):
    """Ucover all hidden tiles (-1) and only provide useful data (id: value)"""

    sanitized_data = {
        id: data['value'] if not data['hidden'] or data['value'] == 9 else -1
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

    if mine_percentage >= 0.5 and size >= 2500:
        return 200
    
    difficulty_bonus_dict = {
        0.2: 25,
        0.3: 50,
        0.5: 75
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

# ROUTES

@app.route('/')
def index():
    return "This is only an api! If you want to access the game, go to <a href=\"https://sapper.malpkakefirek.repl.co/\">https://sapper.malpkakefirek.repl.co</a>"

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
                'response': 'db error'
            }
            cursor.close()
            return jsonify(data), 500
    except Exception as e:
        cursor.close()
        return jsonify({'error': str(e)}), 500

@app.route('/login', methods=['POST'])
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
            print("1")
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
            print("2")
            cursor.close()
            return jsonify({"type":"fail", "reason":"username or password is incorrect"}), 200
    
        print("3")
        sql = "with rows as (INSERT INTO sessions (user_id) VALUES (%s) RETURNING session_id) SELECT session_id FROM rows"
        values = (uuid, )
        cursor.execute(sql, values)
        conn.commit()
        session = cursor.fetchone()
        cursor.close()
    
        if not session:
            print("4")
            return jsonify({"type":"fail", "reason":"unknown error"}), 500
    
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
        return jsonify({'error': str(e)}), 500    

@app.route('/register', methods=['POST'])
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
            print("1")
            cursor.close()
            return jsonify({"type":"fail", "reason":"account with this email already exists"}), 200
            
        sql = "SELECT uuid FROM users WHERE username = %s"
        values = (username, )
        cursor.execute(sql, values)
        existing_username = cursor.fetchone()
    
        if existing_username:
            print("2")
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
            print("3")
            cursor.close()
            return jsonify({"type":"fail", "reason":"unknown error"}), 500
        print(f"created account {user[0]} with email {user[1]}")
        
        sql = "with rows as (INSERT INTO sessions (user_id) VALUES (%s) RETURNING session_id) SELECT session_id FROM rows"
        values = (user[0], )
        cursor.execute(sql, values)
        session = cursor.fetchone()
        cursor.close()
    
        if not session:
            print("4")
            return jsonify({"type":"fail", "reason":"unknown error"}), 500
    
        print(f"and session_id {session[0]}")
        return jsonify({
            "type": "success", 
            "session_id": session[0],
            "username": username
        }), 200
    except Exception as e:
        cursor.close()
        return jsonify({'error': str(e)}), 500

@app.route('/logout', methods=['POST'])
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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        print(user_skins)
        
        
        # sql = "SELECT * FROM skins WHERE sid = ANY(%s)"
        # values = (user_skins,)
        # cursor.execute(sql, values)
        # skins = cursor.fetchall()
        # cursor.close()

        # data = {}
        # for skin in skins:
        #     skin_id = skin[0]
        #     skin_name = skin[1]
        #     price_coins = skin[2]
        #     price_gems = skin[3]

        #     data[str(skin_id)] = {
        #         'name': skin_name,
        #         'price_coins': price_coins,
        #         'price_gems': price_gems
        #     }
        return jsonify({"ids": user_skins}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500
    

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
        return jsonify({'error': str(e)}), 500

@app.route('/click_tile', methods=['POST'])
@cross_origin()
def click_tile():
    session_id = request.json['session_id']
    tile_id = request.json['tile_id']
    print(session_id)
    print(tile_id)

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
        
        sql = "SELECT data FROM games WHERE game_id = %s"
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

        start_time = False
        if not game_data['timer_started']:
            game_data['timer_started'] = True
            sql = "WITH row AS (UPDATE games SET data = %s, start_time = NOW() WHERE game_id = %s RETURNING start_time) SELECT extract(epoch from start_time)::integer FROM row"
            values = (json.dumps(game_data), session_id)
            cursor.execute(sql, values)
            conn.commit()
            start_time = cursor.fetchone()[0]
        
        tiles = game_data['tiles']
        
        # id not found
        if tile_id not in tiles:
            cursor.close()
            return jsonify({"type": "fail", "reason": "tile not found"}), 404

        # Already clicked (not hidden)
        if not tiles[tile_id]['hidden']:
            cursor.close()
            return jsonify({"type": "fail", "reason": "tile already clicked"}), 400

        # Loss condition
        if tiles[tile_id]['value'] == 9:
            cursor.close()
            
            # Delete game from database in another thread
            thread = Thread(
                target=delete_game_from_database, 
                kwargs={'session_id': session_id}
            )
            thread.start()

            tiles[tile_id]['value'] = 10 # Blow up mine visually
            game_data['tiles'] = tiles
            return jsonify({
                'type': "loss", 
                'board': uncover_all_mines(game_data)
            }), 200

        # Uncover tiles, because a number tile got clicked
        if tiles[tile_id]['value'] in range(1, 9):
            tiles[tile_id]['hidden'] = False
        elif tiles[tile_id]['value'] == 0:
            tiles = uncover_tiles(tiles, game_data['size_x'], game_data['size_y'], tile_id)
        else:
            cursor.close()
            return jsonify({"type": "fail", "reason": "unknown tile value"}), 500

        game_data['tiles'] = tiles
        
        # Win condition
        if count_hidden_tiles(tiles) == game_data['mine_count']:
            # Calculate XP
            added_xp = calculate_xp(
                game_data['mine_count'], 
                game_data['size_x'] * game_data['size_y']
            )
            
            # Add XP and Battlepass XP
            sql = "WITH row AS (UPDATE users SET xp = xp+%s, bp_xp = bp_xp+%s WHERE uuid = %s RETURNING xp, bp_xp) SELECT xp, bp_xp FROM row"
            values = (added_xp, added_xp, user_id)
            cursor.execute(sql, values)
            conn.commit()
            user = cursor.fetchone()

            if not user:
                cursor.close()
                return jsonify({"type": "fail", "reason": "unknown error fetching user"}), 500

            user_xp = user[0]
            user_battlepass_xp = user[1]
            
            cursor.close()

            # Delete game from database in another thread
            thread = Thread(
                target=delete_game_from_database, 
                kwargs={'session_id': session_id}
            )
            thread.start()

            # TODO: give reward to player and pass it to the client

            board = sanitize_game_data(game_data)
            result = jsonify({
                "type": "win", 
                "board": board,
                "added_xp": added_xp,
                "xp": user_xp,
                "battlepass_xp": user_battlepass_xp
            })
            return result, 200

        # Update game state in database
        sql = "UPDATE games SET data = %s WHERE game_id = %s"
        values = (json.dumps(game_data), session_id)
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        
        board = sanitize_game_data(game_data)
        result = {
            'type': "playing",
            'board': board,
        }
        if start_time:
            result['start_time'] = start_time
        return jsonify(result), 200
    except Exception as e:
        cursor.close()
        return jsonify({'error': str(e)}), 500

@app.route('/debug_game_creation')
def debug_game_creation():
    game_board = create_game_board(50, 50, 400)
    game_data = {
        id: {'value': value, 'hidden': True} 
        for id, value in enumerate(game_board)
    }
    result = {
        id: data['value'] if not data['hidden'] else -1
        for id, data in game_data.items()
    }
    return jsonify(result), 200

@app.route('/debug_calculate/<size>')
def debug_calculate(size):
    size = int(size)
    result = {}
    for mines in range(0, size*size, max(int(size/10),1)):
        result[f"{size}x{size} - {mines} mines"] = calculate_xp(mines,size*size)
    return jsonify(result), 200

# !! TO DO !!
# @app.route('/retrieve_levels', methods=['POST'])
# @cross_origin()
# def retrieve_levels():
#     # Retrieve player   level, xp, max_xp, battlepass_level, battlepass_xp, max_battlepass_xp
#     session_id = request.json['session_id']
#     try:
#         cursor = conn.cursor()
#         sql = "SELECT user_id FROM sessions WHERE session_id = %s"
#         values = (session_id,)
#         cursor.execute(sql, values)
#         row = cursor.fetchone()

#         if not row:
#             cursor.close()
#             return jsonify({"type": "fail", "reason": "wrong session id"}), 401

#         sql = "SELECT xp,bp_xp FROM users WHERE ... = %s"
#         values = (session_id,)
#         cursor.execute(sql, values)
#         row = cursor.fetchone()

    
#     except Exception as e:
#         cursor.close()
#         return jsonify({'error': str(e)}), 500

@app.route('/create_game', methods=['POST'])
@cross_origin()
def create_game():
    # [session_id, size_x, size_y, mine_count]
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
    
        sql = "SELECT data FROM games WHERE game_id = %s"
        values = (session_id,)
        cursor.execute(sql, values)
        game = cursor.fetchone()
    
        # Delete old game if left in database
        if game:
            sql = "DELETE FROM games WHERE game_id = %s"
            values = (session_id,)
            cursor.execute(sql, values)
            conn.commit()
            print(f"deleted old game for session {session_id}")
    
        # Creating game data
        size_x = request.json['size_x']
        size_y = request.json['size_y']
        mine_count = request.json['mine_count']
        game_board = create_game_board(size_x, size_y, mine_count)
        game_data = {
            'tiles': {
                id: {'value': value, 'hidden': True} 
                for id, value in enumerate(game_board)
            },
            'size_x': size_x,
            'size_y': size_y,
            'mine_count': mine_count,
            'timer_started': False
        }
        sql = "INSERT INTO games (game_id, data) VALUES (%s, %s)"
        values = (session_id, json.dumps(game_data))
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        
        return jsonify({"type": "success"}), 200
    except Exception as e:
        cursor.close()
        return jsonify({'error': str(e)}), 500
