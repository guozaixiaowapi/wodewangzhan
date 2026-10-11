# -*- coding: utf-8 -*-
import os
import json
import time
import hashlib
import jwt
import re
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

OSS_PREFIX = 'huiyuanzhongxin/'
LOG_PREFIX = 'rizhi/'

# ---------- 工具 ----------
def get_oss_client():
    auth = oss2.Auth(ACCESS_KEY_ID, ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f'http://oss-{REGION}.aliyuncs.com', BUCKET_NAME)


def generate_jwt(user):
    payload = {
        'account': user['account'],
        'role': user['role'],
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
        if request.current_user.get('role') not in ['master', 'sub']:
            return jsonify({'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated


def log_operation(account, operation, target, details=''):
    try:
        bucket = get_oss_client()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts} | {operation} | {target} | {details}\n"
        key = f'{LOG_PREFIX}{account}.txt'
        try:
            obj = bucket.get_object(key)
            existing = obj.read().decode('utf-8')
            new_content = existing + line
        except oss2.exceptions.NoSuchKey:
            new_content = line
        bucket.put_object(key, new_content.encode('utf-8'))
    except Exception as e:
        print(f'日志写入失败: {e}')


# ---------- 数据文件 ----------
USERS_FILE = OSS_PREFIX + 'users.json'
LEVELS_FILE = OSS_PREFIX + 'levels.json'

DEFAULT_LEVELS = [
    "铜", "银", "金", "钻",
    "钻（王者）", "钻（荣耀）", "钻（王者（荣耀））", "钻（荣耀（荣耀））",
    "王者（铜）", "王者（银）", "王者（金）", "王者（钻）", "王者（王者）", "王者（荣耀）",
    "荣耀（铜）", "荣耀（银）", "荣耀（金）", "荣耀（钻）", "荣耀（王者）", "荣耀（荣耀）",
    "王者（极王者）", "王者（极荣耀）", "荣耀（极王者）", "荣耀（极荣耀）",
    "王者【（极王者）】", "王者【（极荣耀）】", "荣耀【（极王者）】", "荣耀【（极荣耀）】",
    "荣耀{极王者}", "荣耀{极荣耀}",
    "极荣耀{【极王者】}", "极荣耀{【极荣耀】}",
    "极荣耀{【（极王者）】}", "极荣耀{【（极荣耀）】}"
]

DEFAULT_MASTER = {
    'account': '201510165483',
    'password': '201516',
    'role': 'master',
    'name': '主管理',
    'level': '铜',
    'points': 0,
    'balance': 0,
    'fixed': True,
    'created_at': int(time.time())
}


def load_users():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(USERS_FILE)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        users = [DEFAULT_MASTER]
        save_users(users)
        return users


def save_users(users):
    bucket = get_oss_client()
    bucket.put_object(USERS_FILE, json.dumps(users, ensure_ascii=False).encode('utf-8'))


def load_levels():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(LEVELS_FILE)
        data = json.loads(obj.read().decode('utf-8'))
        return data.get('levels', DEFAULT_LEVELS)
    except oss2.exceptions.NoSuchKey:
        save_levels(DEFAULT_LEVELS)
        return DEFAULT_LEVELS


def save_levels(levels):
    bucket = get_oss_client()
    bucket.put_object(LEVELS_FILE, json.dumps({'levels': levels}, ensure_ascii=False).encode('utf-8'))


# ---------- 登录 ----------
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    account = data.get('account', '').strip()
    password = data.get('password', '').strip()
    if not account or not password:
        return jsonify({'error': '请输入卡号和密码'}), 400

    users = load_users()
    user = next((u for u in users if u['account'] == account), None)
    if not user:
        return jsonify({'error': '卡号不存在'}), 401
    if user['password'] != password:
        return jsonify({'error': '密码错误'}), 401

    token = generate_jwt(user)
    log_operation(account, 'login', account, '登录成功')
    return jsonify({
        'token': token,
        'user': {k: v for k, v in user.items() if k != 'password'}
    })


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    users = load_users()
    user = next((u for u in users if u['account'] == request.current_user['account']), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': {k: v for k, v in user.items() if k != 'password'}})


# ---------- 用户列表 ----------
@app.route('/api/users/list', methods=['GET'])
@require_admin
def list_users():
    role = request.current_user.get('role')
    users = load_users()
    if role == 'sub':
        users = [u for u in users if u['role'] != 'master']
    safe = [{k: v for k, v in u.items() if k != 'password'} for u in users]
    return jsonify({'users': safe})


# ---------- 添加用户 ----------
@app.route('/api/users/add', methods=['POST'])
@require_admin
def add_user():
    role = request.current_user.get('role')
    data = request.json or {}
    account = data.get('account', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    user_role = data.get('role', 'member')
    level = data.get('level', DEFAULT_LEVELS[0])
    points = int(data.get('points', 0) or 0)
    balance = float(data.get('balance', 0) or 0)

    if not re.match(r'^\d{12}$', account):
        return jsonify({'error': '卡号必须为12位数字'}), 400
    if not password or len(password) < 4:
        return jsonify({'error': '密码至少4位'}), 400

    users = load_users()
    if any(u['account'] == account for u in users):
        return jsonify({'error': '卡号已存在'}), 400

    if role == 'sub' and user_role not in ['sub', 'member']:
        return jsonify({'error': '副管理只能添加副管理或会员'}), 403
    if user_role == 'master' and sum(1 for u in users if u['role'] == 'master') >= 2:
        return jsonify({'error': '主管理最多2人'}), 400
    if user_role == 'sub' and sum(1 for u in users if u['role'] == 'sub') >= 5:
        return jsonify({'error': '副管理最多5人'}), 400

    users.append({
        'account': account,
        'password': password,
        'role': user_role,
        'name': name,
        'level': level,
        'points': points,
        'balance': balance,
        'fixed': False,
        'created_at': int(time.time())
    })
    save_users(users)
    log_operation(request.current_user['account'], 'add_user', account, f'角色:{user_role}')
    return jsonify({'message': '添加成功'})


# ---------- 编辑用户 ----------
@app.route('/api/users/edit', methods=['POST'])
@require_auth
def edit_user():
    current = request.current_user
    data = request.json or {}
    account = data.get('account', '').strip()
    if not account:
        return jsonify({'error': '缺少卡号'}), 400

    users = load_users()
    user = next((u for u in users if u['account'] == account), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    is_self = (account == current['account'])
    role = current['role']

    if not is_self and role not in ['master', 'sub']:
        return jsonify({'error': '权限不足'}), 403
    if not is_self and role == 'sub' and user['role'] in ['master', 'sub']:
        return jsonify({'error': '副管理不能修改主管理或副管理'}), 403

    if 'name' in data and data['name']:
        user['name'] = data['name']
    if 'level' in data and data['level']:
        user['level'] = data['level']
    if 'password' in data and data['password']:
        if len(data['password']) < 4:
            return jsonify({'error': '密码至少4位'}), 400
        user['password'] = data['password']

    if role in ['master', 'sub']:
        if 'points' in data:
            user['points'] = int(data['points'] or 0)
        if 'balance' in data:
            user['balance'] = float(data['balance'] or 0)

    save_users(users)
    log_operation(current['account'], 'edit_user', account, '编辑用户信息')
    return jsonify({'message': '修改成功'})


# ---------- 删除用户 ----------
@app.route('/api/users/delete', methods=['POST'])
@require_admin
def delete_user():
    current = request.current_user
    data = request.json or {}
    account = data.get('account', '').strip()
    users = load_users()
    user = next((u for u in users if u['account'] == account), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if user.get('fixed'):
        return jsonify({'error': '固定用户不能删除'}), 403
    if account == current['account']:
        return jsonify({'error': '不能删除自己'}), 403
    if current['role'] == 'sub' and user['role'] in ['master', 'sub']:
        return jsonify({'error': '副管理不能删除主管理或副管理'}), 403

    users = [u for u in users if u['account'] != account]
    save_users(users)
    log_operation(current['account'], 'delete_user', account, '删除用户')
    return jsonify({'message': '删除成功'})


# ---------- 充值 / 扣款 ----------
@app.route('/api/users/charge', methods=['POST'])
@require_auth
def charge():
    current = request.current_user
    if current['role'] != 'master':
        return jsonify({'error': '只有主管理能操作余额'}), 403
    data = request.json or {}
    account = data.get('account', '').strip()
    amount = float(data.get('amount', 0))
    direction = int(data.get('direction', 1))
    if amount <= 0:
        return jsonify({'error': '金额必须大于0'}), 400

    users = load_users()
    user = next((u for u in users if u['account'] == account), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if account == current['account']:
        return jsonify({'error': '不能对自己操作'}), 403

    new_balance = user.get('balance', 0) + amount * direction
    if new_balance < 0:
        return jsonify({'error': '扣款后余额不能为负'}), 400
    user['balance'] = round(new_balance, 2)
    save_users(users)
    action = '充值' if direction == 1 else '扣款'
    log_operation(current['account'], action, account, f'金额:{amount}')
    return jsonify({'message': f'{action}成功', 'balance': user['balance']})


# ---------- 等级 ----------
@app.route('/api/levels/list', methods=['GET'])
def levels_list():
    return jsonify({'levels': load_levels()})


@app.route('/api/levels/add', methods=['POST'])
@require_auth
def levels_add():
    if request.current_user['role'] != 'master':
        return jsonify({'error': '只有主管理能管理等级'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '等级名不能为空'}), 400
    levels = load_levels()
    if name in levels:
        return jsonify({'error': '等级已存在'}), 400
    levels.append(name)
    save_levels(levels)
    log_operation(request.current_user['account'], 'add_level', name, '')
    return jsonify({'message': '添加成功', 'levels': levels})


@app.route('/api/levels/delete', methods=['POST'])
@require_auth
def levels_delete():
    if request.current_user['role'] != 'master':
        return jsonify({'error': '只有主管理能管理等级'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    levels = load_levels()
    if name not in levels:
        return jsonify({'error': '等级不存在'}), 404
    levels.remove(name)
    save_levels(levels)
    log_operation(request.current_user['account'], 'delete_level', name, '')
    return jsonify({'message': '删除成功', 'levels': levels})


# ---------- 健康检查 ----------
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)