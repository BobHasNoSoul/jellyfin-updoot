from flask import Flask, jsonify, request
import sqlite3
import os
import logging
import requests
import time

app = Flask(__name__)
DATABASE = './recommendations.db'  # where your database lives.. usually same dir default ./recommendations.db
JELLYFIN_URL = 'https://DOMAINNAMEHERE' # Replace with your domain name inc http:// or https://
JELLYFIN_API_KEY = 'APIKEYHERE'  # Replace with actual Jellyfin API key
ADMIN_USER_IDS = ['USERID1', 'USERID2']  # Replace with actual admin user IDs

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s',
    filename='./flask-app.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

def init_db():
    logger.debug('Initializing database at %s', DATABASE)
    try:
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        with sqlite3.connect(DATABASE) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS recommendations
                         (userId TEXT, itemId TEXT, username TEXT, timestamp INTEGER DEFAULT (strftime('%s', 'now')))''')
            c.execute('''CREATE TABLE IF NOT EXISTS comments
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, userId TEXT, itemId TEXT, username TEXT, comment TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS settings
                         (globalLimit INTEGER, userId TEXT, perUserLimit INTEGER)''')
            c.execute('INSERT OR IGNORE INTO settings (globalLimit, userId, perUserLimit) VALUES (0, NULL, NULL)')

            c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_timestamp ON recommendations(timestamp)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_itemid ON recommendations(itemId)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_userid ON recommendations(userId)')

            conn.commit()
        logger.info('Database initialized successfully at %s', DATABASE)
    except sqlite3.OperationalError as e:
        logger.error('Failed to initialize database: %s', str(e))
        raise

def get_db():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logger.error('Failed to connect to database: %s', str(e))
        raise

def get_jellyfin_username(userId):
    try:
        url = f'{JELLYFIN_URL}/Users/{userId}?api_key={JELLYFIN_API_KEY}'
        response = requests.get(url)
        if response.ok:
            return response.json().get('Name', f'User_{userId[:8]}')
        return f'User_{userId[:8]}'
    except Exception as e:
        logger.error('Error fetching username for userId=%s: %s', userId, str(e))
        return f'User_{userId[:8]}'

@app.route('/updoot/recommend', methods=['POST'])
def recommend():
    try:
        data = request.get_json()
        userId = data.get('userId')
        itemId = data.get('itemId')
        if not userId or not itemId:
            return jsonify({'error': 'Missing userId or itemId'}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT globalLimit FROM settings WHERE ROWID = 1')
            globalLimit = c.fetchone()
            globalLimit = globalLimit['globalLimit'] if globalLimit else 0
            if globalLimit > 0:
                c.execute('SELECT COUNT(*) as count FROM recommendations')
                if c.fetchone()['count'] >= globalLimit:
                    return jsonify({'error': 'Global recommendation limit reached'}), 403

            c.execute('SELECT perUserLimit FROM settings WHERE userId = ?', (userId,))
            userLimitRow = c.fetchone()
            userLimit = userLimitRow['perUserLimit'] if userLimitRow else 0
            if userLimit > 0:
                c.execute('SELECT COUNT(*) as count FROM recommendations WHERE userId = ?', (userId,))
                if c.fetchone()['count'] >= userLimit:
                    return jsonify({'error': 'User recommendation limit reached'}), 403

            username = get_jellyfin_username(userId)
            c.execute('SELECT * FROM recommendations WHERE userId = ? AND itemId = ?', (userId, itemId))
            if c.fetchone():
                c.execute('DELETE FROM recommendations WHERE userId = ? AND itemId = ?', (userId, itemId))
                conn.commit()
                return jsonify({'status': 'unrecommended'})
            else:
                timestamp = int(time.time())
                c.execute('INSERT INTO recommendations (userId, itemId, username, timestamp) VALUES (?, ?, ?, ?)',
                          (userId, itemId, username, timestamp))
                conn.commit()
                return jsonify({'status': 'recommended'})
    except Exception as e:
        logger.error('Error in /recommend: %s', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/recommendations', methods=['GET'])
def get_recommendations():
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT userId, itemId, username, timestamp FROM recommendations ORDER BY timestamp DESC')
            recommendations = [{
                'userId': row['userId'],
                'itemId': row['itemId'],
                'username': row['username'],
                'timestamp': row['timestamp']
            } for row in c.fetchall()]
            return jsonify(recommendations)
    except Exception as e:
        logger.error('Error in /recommendations: %s', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/recommendations/<itemId>', methods=['GET'])
def get_recommendations_for_item(itemId):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT userId, itemId, username, timestamp FROM recommendations WHERE itemId = ? ORDER BY timestamp DESC', (itemId,))
            recommendations = [{
                'userId': row['userId'],
                'itemId': row['itemId'],
                'username': row['username'],
                'timestamp': row['timestamp']
            } for row in c.fetchall()]
            return jsonify(recommendations)
    except Exception as e:
        logger.error('Error in /recommendations/%s: %s', itemId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/comments', methods=['POST'])
def add_comment():
    try:
        data = request.get_json()
        userId = data.get('userId')
        itemId = data.get('itemId')
        comment = data.get('comment')
        if not userId or not itemId or not comment:
            return jsonify({'error': 'Missing userId, itemId, or comment'}), 400

        username = get_jellyfin_username(userId)
        with get_db() as conn:
            c = conn.cursor()
            c.execute('INSERT INTO comments (userId, itemId, username, comment) VALUES (?, ?, ?, ?)',
                      (userId, itemId, username, comment))
            conn.commit()
        return jsonify({'status': 'comment added'})
    except Exception as e:
        logger.error('Error in /comments: %s', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/comments/<itemId>', methods=['GET'])
def get_comments_for_item(itemId):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, userId, itemId, username, comment FROM comments WHERE itemId = ?', (itemId,))
            comments = [{
                'id': row['id'],
                'userId': row['userId'],
                'itemId': row['itemId'],
                'username': row['username'],
                'comment': row['comment']
            } for row in c.fetchall()]
            return jsonify(comments)
    except Exception as e:
        logger.error('Error in /comments/%s: %s', itemId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/comments/<int:commentId>', methods=['PUT'])
def edit_comment(commentId):
    try:
        data = request.get_json()
        userId = data.get('userId')
        comment = data.get('comment')
        if not userId or not comment:
            return jsonify({'error': 'Missing userId or comment'}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT userId FROM comments WHERE id = ?', (commentId,))
            result = c.fetchone()
            if not result:
                return jsonify({'error': 'Comment not found'}), 404
            if result['userId'] != userId and userId not in ADMIN_USER_IDS:
                return jsonify({'error': 'Unauthorized'}), 403
            c.execute('UPDATE comments SET comment = ? WHERE id = ?', (comment, commentId))
            conn.commit()
        return jsonify({'status': 'comment edited'})
    except Exception as e:
        logger.error('Error in /comments/%s: %s', commentId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/comments/<int:commentId>', methods=['DELETE'])
def delete_comment(commentId):
    try:
        data = request.get_json()
        userId = data.get('userId')
        if not userId:
            return jsonify({'error': 'Missing userId'}), 400

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT userId FROM comments WHERE id = ?', (commentId,))
            result = c.fetchone()
            if not result:
                return jsonify({'error': 'Comment not found'}), 404
            if result['userId'] != userId and userId not in ADMIN_USER_IDS:
                return jsonify({'error': 'Unauthorized'}), 403
            c.execute('DELETE FROM comments WHERE id = ?', (commentId,))
            conn.commit()
        return jsonify({'status': 'comment deleted'})
    except Exception as e:
        logger.error('Error in /comments/%s: %s', commentId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/admin/comments', methods=['GET'])
def get_all_comments():
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id, userId, itemId, username, comment FROM comments')
            comments = [{
                'id': row['id'],
                'userId': row['userId'],
                'itemId': row['itemId'],
                'username': row['username'],
                'comment': row['comment']
            } for row in c.fetchall()]
            return jsonify(comments)
    except Exception as e:
        logger.error('Error in /admin/comments: %s', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/admin/comments/<int:commentId>', methods=['DELETE'])
def delete_admin_comment(commentId):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM comments WHERE id = ?', (commentId,))
            if c.rowcount == 0:
                return jsonify({'error': 'Comment not found'}), 404
            conn.commit()
        return jsonify({'status': 'comment deleted'})
    except Exception as e:
        logger.error('Error in /admin/comments/%s: %s', commentId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/admin/comments/user/<userId>', methods=['DELETE'])
def delete_comments_by_user(userId):
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM comments WHERE userId = ?', (userId,))
            conn.commit()
        return jsonify({'status': 'comments deleted for user'})
    except Exception as e:
        logger.error('Error in /admin/comments/user/%s: %s', userId, str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/admin/settings', methods=['GET'])
def get_settings():
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT globalLimit FROM settings WHERE ROWID = 1')
            globalLimit = c.fetchone()
            c.execute('SELECT userId, perUserLimit FROM settings WHERE userId IS NOT NULL')
            userLimits = {row['userId']: row['perUserLimit'] for row in c.fetchall()}
            return jsonify({
                'globalLimit': globalLimit['globalLimit'] if globalLimit else 0,
                'userLimits': userLimits
            })
    except Exception as e:
        logger.error('Error in /admin/settings: %s', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/updoot/admin/settings', methods=['POST'])
def save_settings():
    try:
        data = request.get_json()
        globalLimit = data.get('globalLimit', 0)
        userId = data.get('userId')
        perUserLimit = data.get('perUserLimit', 0)

        with get_db() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM settings WHERE ROWID = 1')
            c.execute('INSERT INTO settings (globalLimit, userId, perUserLimit) VALUES (?, NULL, NULL)', (globalLimit,))
            if userId:
                c.execute('DELETE FROM settings WHERE userId = ?', (userId,))
                c.execute('INSERT INTO settings (globalLimit, userId, perUserLimit) VALUES (NULL, ?, ?)',
                          (userId, perUserLimit))
            conn.commit()
        return jsonify({'status': 'settings saved'})
    except Exception as e:
        logger.error('Error in /admin/settings: %s', str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        logger.info('Database not found, initializing')
        init_db()
    else:
        logger.info('Existing database found, upgrading schema...')
        try:
            with sqlite3.connect(DATABASE) as conn:
                c = conn.cursor()
                c.execute("PRAGMA table_info(recommendations)")
                columns = [col[1] for col in c.fetchall()]
                if 'timestamp' not in columns:
                    c.execute('ALTER TABLE recommendations ADD COLUMN timestamp INTEGER DEFAULT (strftime("%s", "now"))')
                    logger.info('Added timestamp column')
                c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_timestamp ON recommendations(timestamp)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_itemid ON recommendations(itemId)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_recommendations_userid ON recommendations(userId)')
                conn.commit()
            logger.info('Database schema upgraded successfully')
        except Exception as e:
            logger.error('Failed to upgrade database schema: %s', str(e))
    app.run(host='0.0.0.0', port=8099, debug=False)
