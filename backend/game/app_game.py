# -*- coding: utf-8 -*-
import os
import json
import time
import jwt
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
import oss2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

ACCESS_KEY_ID = config['OSS_ACCESS_KEY_ID']
ACCESS_KEY_SECRET = config['OSS_ACCESS_KEY_SECRET']
JWT_SECRET = config.get('JWT_SECRET', 'your-secret-key-change-me')
REGION = config.get('REGION', 'cn-chengdu')
BUCKET_NAME = 'aliyun-wangzhan1'

OSS_PREFIX = 'youxizhongxin/'
LOG_PREFIX = 'rizhi/'

COURSES_FILE = OSS_PREFIX + 'courses.json'
AI_CONFIG_FILE = OSS_PREFIX + 'ai_config.json'

# 主界面角色 -> 游戏中心角色
ROLE_MAP = {
    'super': 'admin',
    'master': 'admin',
    'deputy': 'sub',
    'user': 'guest'
}

DEFAULT_AI_CONFIG = {
    'apiKey': '',
    'model': 'deepseek-v4-flash',
    'apiUrl': 'https://api.deepseek.com/v1/chat/completions',
    'saveHistory': True
}


# ---------- OSS ----------
def get_oss_client():
    auth = oss2.Auth(ACCESS_KEY_ID, ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f'http://oss-{REGION}.aliyuncs.com', BUCKET_NAME)


# ---------- JWT ----------
def generate_jwt(user):
    payload = {
        'phone': user['phone'],
        'role': user.get('role', 'guest'),
        'exp': datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def decode_jwt(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return {'error': '令牌已过期'}
    except jwt.InvalidTokenError:
        return {'error': '无效令牌'}


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth or not auth.startswith('Bearer '):
            return jsonify({'error': '请先登录'}), 401
        token = auth.split(' ')[1]
        payload = decode_jwt(token)
        if 'error' in payload:
            return jsonify({'error': payload['error']}), 401
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if request.current_user.get('role') != 'admin':
            return jsonify({'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated


# ---------- 日志 ----------
def log_operation(phone, operation, details=''):
    try:
        bucket = get_oss_client()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts} | {operation} | {details}\n"
        key = f'{LOG_PREFIX}{phone}.txt'
        try:
            obj = bucket.get_object(key)
            existing = obj.read().decode('utf-8')
            new_content = existing + line
        except oss2.exceptions.NoSuchKey:
            new_content = line
        bucket.put_object(key, new_content.encode('utf-8'))
    except Exception as e:
        print(f'日志写入失败: {e}')


# ---------- 用户数据文件 ----------
def user_score_key(phone):
    return f'{OSS_PREFIX}{phone}/scores.json'


def user_learning_key(phone):
    return f'{OSS_PREFIX}{phone}/learning.json'


def read_json(key, default=None):
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(key)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        return default if default is not None else {}


def write_json(key, data):
    bucket = get_oss_client()
    bucket.put_object(key, json.dumps(data, ensure_ascii=False).encode('utf-8'))


# ---------- SSO ----------
@app.route('/api/auth/sso', methods=['POST'])
def sso_login():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    name = data.get('name', '').strip()
    main_role = data.get('role', 'user')

    if not phone:
        return jsonify({'error': '缺少手机号'}), 400

    game_role = ROLE_MAP.get(main_role, 'guest')

    token = generate_jwt({'phone': phone, 'role': game_role})
    log_operation(phone, 'sso_login', f'角色:{game_role}')

    return jsonify({
        'token': token,
        'user': {
            'phone': phone,
            'name': name or phone,
            'role': game_role
        }
    })


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    return jsonify({'user': request.current_user})


# ---------- 分数 ----------
@app.route('/api/scores/get', methods=['GET'])
@require_auth
def scores_get():
    phone = request.current_user['phone']
    scores = read_json(user_score_key(phone), {})
    return jsonify({'scores': scores})


@app.route('/api/scores/save', methods=['POST'])
@require_auth
def scores_save():
    phone = request.current_user['phone']
    data = request.json or {}
    game_id = data.get('gameId', '').strip()
    score = int(data.get('score', 0) or 0)

    if not game_id:
        return jsonify({'error': '缺少游戏ID'}), 400

    scores = read_json(user_score_key(phone), {})
    prev = scores.get(game_id, 0)
    if score > prev:
        scores[game_id] = score
        write_json(user_score_key(phone), scores)
        log_operation(phone, 'game_score', f'{game_id}:{score}')

    return jsonify({'scores': scores, 'best': scores.get(game_id, 0)})


# ---------- 学习进度 ----------
@app.route('/api/learning/get', methods=['GET'])
@require_auth
def learning_get():
    phone = request.current_user['phone']
    learning = read_json(user_learning_key(phone), {})
    return jsonify({'learning': learning})


@app.route('/api/learning/save', methods=['POST'])
@require_auth
def learning_save():
    phone = request.current_user['phone']
    data = request.json or {}
    course_id = data.get('courseId', '').strip()
    progress = int(data.get('progress', 0) or 0)

    if not course_id:
        return jsonify({'error': '缺少课程ID'}), 400

    progress = max(0, min(100, progress))
    learning = read_json(user_learning_key(phone), {})
    learning[course_id] = progress
    write_json(user_learning_key(phone), learning)
    log_operation(phone, 'learning_progress', f'{course_id}:{progress}%')

    return jsonify({'learning': learning})


# ---------- 课程 ----------
@app.route('/api/courses/list', methods=['GET'])
def courses_list():
    courses = read_json(COURSES_FILE, None)
    if courses is None:
        return jsonify({'courses': []})
    return jsonify({'courses': courses})


@app.route('/api/courses/save', methods=['POST'])
@require_admin
def courses_save():
    data = request.json or {}
    courses = data.get('courses', [])
    write_json(COURSES_FILE, courses)
    log_operation(request.current_user['phone'], 'save_courses', f'共{len(courses)}门')
    return jsonify({'message': '保存成功'})


# ---------- AI 配置 ----------
@app.route('/api/ai/config/get', methods=['GET'])
def ai_config_get():
    cfg = read_json(AI_CONFIG_FILE, None)
    if cfg is None:
        cfg = DEFAULT_AI_CONFIG
    # 不返回完整 key，返回掩码
    safe = dict(cfg)
    if safe.get('apiKey'):
        safe['apiKey'] = safe['apiKey'][:8] + '****'
    return jsonify({'config': safe, 'has_key': bool(cfg.get('apiKey'))})


@app.route('/api/ai/config/save', methods=['POST'])
@require_admin
def ai_config_save():
    data = request.json or {}
    cfg = read_json(AI_CONFIG_FILE, DEFAULT_AI_CONFIG)

    if 'apiKey' in data and data['apiKey']:
        cfg['apiKey'] = data['apiKey']
    if 'model' in data:
        cfg['model'] = data['model']
    if 'apiUrl' in data:
        cfg['apiUrl'] = data['apiUrl']
    if 'saveHistory' in data:
        cfg['saveHistory'] = bool(data['saveHistory'])

    write_json(AI_CONFIG_FILE, cfg)
    log_operation(request.current_user['phone'], 'save_ai_config', f'模型:{cfg.get("model")}')
    return jsonify({'message': '保存成功'})


# ---------- AI 对话（代理） ----------
@app.route('/api/ai/chat', methods=['POST'])
@require_auth
def ai_chat():
    """前端传消息过来，后端用配置里的 key 调真实 AI"""
    import requests as http_requests

    cfg = read_json(AI_CONFIG_FILE, DEFAULT_AI_CONFIG)
    if not cfg.get('apiKey'):
        return jsonify({'error': 'AI 未配置，请联系管理员'}), 500

    data = request.json or {}
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'error': '消息为空'}), 400

    api_url = cfg.get('apiUrl', 'https://api.deepseek.com/v1/chat/completions').rstrip('/')
    if not api_url.endswith('/chat/completions'):
        api_url += '/chat/completions'

    try:
        resp = http_requests.post(
            api_url,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + cfg['apiKey']
            },
            json={
                'model': cfg.get('model', 'deepseek-v4-flash'),
                'messages': messages,
                'temperature': 0.7,
                'max_tokens': 2048,
                'stream': False
            },
            timeout=60
        )
    except Exception as e:
        return jsonify({'error': f'AI 请求失败：{e}'}), 500

    if not resp.ok:
        detail = ''
        try:
            detail = resp.text[:200]
        except Exception:
            pass
        return jsonify({'error': f'HTTP {resp.status_code}: {detail}'}), 500

    result = resp.json()
    content = ''
    if result.get('choices') and result['choices'][0].get('message'):
        content = result['choices'][0]['message'].get('content', '')

    log_operation(request.current_user['phone'], 'ai_chat', f'长度:{len(content)}')
    return jsonify({'content': content})


# ---------- 健康检查 ----------
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=False)