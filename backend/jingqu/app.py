# -*- coding: utf-8 -*-
import os
import json
import time
import random
import hashlib
import jwt
import re
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import oss2
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.join(BASE_DIR, '..', 'frontend')

app = Flask(__name__, static_folder=PARENT_DIR, static_url_path='/static')
CORS(app, resources={r"/api/*": {"origins": "*"}})

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["2000 per day", "500 per hour"]
)

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

ACCESS_KEY_ID = config['OSS_ACCESS_KEY_ID']
ACCESS_KEY_SECRET = config['OSS_ACCESS_KEY_SECRET']
API_TOKEN = config.get('API_TOKEN', 'jingquguanliqi2015')
JWT_SECRET = config.get('JWT_SECRET', 'your-secret-key-change-me')
REGION = config.get('REGION', 'cn-chengdu')
BUCKET_NAME = 'aliyun-wangzhan1'

OSS_PREFIX = 'jingquguanliqi/'
LOG_PREFIX = 'rizhi/'

# 主界面角色 -> 景区管理器角色
ROLE_MAP = {
    'super': 'master',
    'master': 'master',
    'deputy': 'deputy',
    'user': 'staff'
}


# ---------- OSS ----------
def get_oss_client():
    auth = oss2.Auth(ACCESS_KEY_ID, ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f'http://oss-{REGION}.aliyuncs.com', BUCKET_NAME)


# ---------- 工具 ----------
def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def generate_jwt(user):
    payload = {
        'phone': user['phone'],
        'name': user.get('name', ''),
        'role': user.get('role', 'staff'),
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
        user = request.current_user
        if user.get('role') not in ['master', 'deputy']:
            return jsonify({'error': '权限不足'}), 403
        return f(*args, **kwargs)
    return decorated


def log_operation(phone, operation, target, details=''):
    try:
        bucket = get_oss_client()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts} | {phone} | {operation} | {target} | {details}\n"
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


# ---------- 用户数据 ----------
USER_FILE_KEY = OSS_PREFIX + 'users.json'


def get_users():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(USER_FILE_KEY)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        default_users = [
            {
                'phone': '18981820927',
                'password_hash': hash_password('guoguo2015'),
                'name': '主管理',
                'role': 'master'
            }
        ]
        bucket.put_object(USER_FILE_KEY, json.dumps(default_users, ensure_ascii=False).encode('utf-8'))
        return default_users


def save_users(users):
    bucket = get_oss_client()
    bucket.put_object(USER_FILE_KEY, json.dumps(users, ensure_ascii=False).encode('utf-8'))


# ---------- API Token 验证 ----------
EXEMPT_PATHS = ['/', '/static', '/api/auth/login', '/api/auth/sso']


@app.before_request
def verify_api_token():
    if request.path in EXEMPT_PATHS or request.path.startswith('/static/'):
        return
    if request.path.startswith('/api/'):
        token = request.headers.get('X-API-Key')
        if not token or token != API_TOKEN:
            return jsonify({'error': '未授权访问'}), 401


# ---------- SSO 登录（主界面进来） ----------
@app.route('/api/auth/sso', methods=['POST'])
def sso_login():
    """主界面进来时调用，手机号+姓名+角色，自动创建或更新用户"""
    data = request.json or {}
    phone = data.get('phone', '').strip()
    name = data.get('name', '').strip()
    main_role = data.get('role', 'user')

    if not phone:
        return jsonify({'error': '缺少手机号'}), 400

    jingqu_role = ROLE_MAP.get(main_role, 'staff')

    users = get_users()
    user = next((u for u in users if u['phone'] == phone), None)

    if not user:
        # 自动创建
        user = {
            'phone': phone,
            'password_hash': hash_password('123456'),
            'name': name or phone,
            'role': jingqu_role
        }
        users.append(user)
        save_users(users)
        log_operation(phone, 'sso_register', phone, f'角色:{jingqu_role}')
    else:
        # 已有则更新姓名和角色
        if name:
            user['name'] = name
        user['role'] = jingqu_role
        save_users(users)

    token = generate_jwt(user)
    log_operation(phone, 'sso_login', phone, f'角色:{user["role"]}')
    return jsonify({
        'token': token,
        'user': {
            'phone': user['phone'],
            'name': user.get('name', ''),
            'role': user['role']
        }
    })


# ---------- 登录（手机号 + 密码） ----------
@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()

    if not phone or not password:
        return jsonify({'error': '请输入手机号和密码'}), 400

    users = get_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '账号不存在'}), 401
    if user.get('password_hash') != hash_password(password):
        return jsonify({'error': '密码错误'}), 401

    token = generate_jwt(user)
    log_operation(phone, 'login', phone, '密码登录')
    return jsonify({
        'token': token,
        'user': {
            'phone': user['phone'],
            'name': user.get('name', ''),
            'role': user.get('role', 'staff')
        }
    })


# ---------- 用户管理 ----------
@app.route('/api/users/list', methods=['GET'])
@require_admin
def list_users():
    users = get_users()
    safe_users = [{k: v for k, v in u.items() if k != 'password_hash'} for u in users]
    return jsonify({'users': safe_users})


@app.route('/api/users/add', methods=['POST'])
@require_admin
def add_user():
    current_user = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    role = data.get('role', 'staff')
    master_pwd = data.get('master_pwd', '').strip()

    if not phone or not password or not name:
        return jsonify({'error': '缺少必要参数'}), 400
    if not re.match(r'^\d{11}$', phone):
        return jsonify({'error': '手机号格式错误'}), 400
    if len(password) < 4:
        return jsonify({'error': '密码至少 4 位'}), 400
    if role not in ['master', 'deputy', 'staff']:
        return jsonify({'error': '角色无效'}), 400

    users = get_users()
    if any(u['phone'] == phone for u in users):
        return jsonify({'error': '手机号已存在'}), 400

    if not master_pwd:
        return jsonify({'error': '请输入主管理密码'}), 400
    if not any(u['role'] == 'master' and u.get('password_hash') == hash_password(master_pwd) for u in users):
        return jsonify({'error': '主管理密码错误'}), 403

    if role == 'master' and sum(1 for u in users if u['role'] == 'master') >= 2:
        return jsonify({'error': '主管理最多 2 人'}), 400
    if role == 'deputy' and sum(1 for u in users if u['role'] == 'deputy') >= 5:
        return jsonify({'error': '副管理最多 5 人'}), 400

    users.append({
        'phone': phone,
        'password_hash': hash_password(password),
        'name': name,
        'role': role
    })
    save_users(users)
    log_operation(current_user['phone'], 'add_user', phone, f'姓名:{name}, 角色:{role}')
    return jsonify({'message': '用户添加成功'})


@app.route('/api/users/delete', methods=['DELETE'])
@require_admin
def delete_user():
    current_user = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()

    if not phone:
        return jsonify({'error': '缺少手机号'}), 400

    users = get_users()
    target = next((u for u in users if u['phone'] == phone), None)
    if not target:
        return jsonify({'error': '用户不存在'}), 404
    if target.get('role') == 'master' and current_user.get('role') != 'master':
        return jsonify({'error': '不能删除主管理'}), 403
    if target.get('phone') == current_user.get('phone'):
        return jsonify({'error': '不能删除自己'}), 403

    users = [u for u in users if u['phone'] != phone]
    save_users(users)
    log_operation(current_user['phone'], 'delete_user', phone, '')
    return jsonify({'message': '用户已删除'})


@app.route('/api/users/change-password', methods=['POST'])
@require_auth
def change_password():
    current_user = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()
    master_pwd = data.get('master_pwd', '').strip()

    if not phone or not new_password:
        return jsonify({'error': '缺少参数'}), 400
    if len(new_password) < 4:
        return jsonify({'error': '新密码至少 4 位'}), 400

    users = get_users()
    target = next((u for u in users if u['phone'] == phone), None)
    if not target:
        return jsonify({'error': '用户不存在'}), 404

    is_self = phone == current_user['phone']

    if not is_self:
        if current_user.get('role') not in ['master', 'deputy']:
            return jsonify({'error': '权限不足'}), 403
        if current_user.get('role') == 'deputy' and target.get('role') == 'master':
            return jsonify({'error': '副管理不能修改主管理密码'}), 403
        if not master_pwd:
            return jsonify({'error': '管理员修改需验证主管理密码'}), 400
        if not any(u['role'] == 'master' and u.get('password_hash') == hash_password(master_pwd) for u in users):
            return jsonify({'error': '主管理密码错误'}), 403
    else:
        if target.get('password_hash') != hash_password(old_password):
            return jsonify({'error': '旧密码错误'}), 403

    target['password_hash'] = hash_password(new_password)
    save_users(users)
    log_operation(current_user['phone'], 'change_password', phone, '')
    return jsonify({'message': '密码已修改'})


# ---------- 门票 ----------
def generate_ticket_id():
    return str(int(time.time() * 1000)) + str(random.randint(1000, 9999))


def split_people(n1, n2):
    n1 = int(n1) if n1 else 0
    n2 = int(n2) if n2 else 0
    if n1 < 0 or n2 < 0:
        return []
    seg_count = max((n1 + 24) // 25, (n2 + 24) // 25)
    if seg_count == 0:
        return [(0, 0)]
    result = []
    r1, r2 = n1, n2
    for _ in range(seg_count):
        part1 = min(r1, 25)
        part2 = min(r2, 25)
        result.append((part1, part2))
        r1 -= part1
        r2 -= part2
    return result


def generate_password():
    return str(random.randint(1000, 9999))


TICKET_PREFIX = OSS_PREFIX + 'tickets/'


@app.route('/api/ticket/generate', methods=['POST'])
@require_auth
@limiter.limit("10 per minute")
def generate_ticket():
    current_user = request.current_user
    data = request.json or {}
    n1 = data.get('num1')
    n2 = data.get('num2')
    valid_date = data.get('valid_date')
    allowed_scene = data.get('allowed_scene', '通用')

    if n1 is None or n2 is None:
        return jsonify({'error': '缺少人数参数'}), 400
    if not valid_date:
        return jsonify({'error': '请选择有效日期'}), 400
    if allowed_scene not in ['通用', '入园', '观光车单程', '观光车往返']:
        return jsonify({'error': '适用场景无效'}), 400

    try:
        n1 = int(n1)
        n2 = int(n2)
    except ValueError:
        return jsonify({'error': '人数必须为数字'}), 400
    if n1 < 0 or n2 < 0:
        return jsonify({'error': '人数不能为负数'}), 400

    try:
        selected_date = datetime.strptime(valid_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': '日期格式错误'}), 400

    expire_datetime = datetime.combine(selected_date, datetime.min.time()) + timedelta(days=1)
    expire_timestamp = int(expire_datetime.timestamp() * 1000)

    segments = split_people(n1, n2)
    if not segments:
        return jsonify({'error': '拆分错误'}), 400

    bucket = get_oss_client()
    results = []

    for a, b in segments:
        ticket_id = generate_ticket_id()
        password = generate_password()
        password_hash = hash_password(password)

        while bucket.object_exists(f'{TICKET_PREFIX}{ticket_id}_status.json'):
            ticket_id = generate_ticket_id()

        status_key = f'{TICKET_PREFIX}{ticket_id}_status.json'
        content = (
            f"门票编号：{ticket_id}\n密码：{password}\n"
            f"入园{a}人，观光车{b}人\n适用场景：{allowed_scene}\n"
            f"有效日期：{valid_date}\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        bucket.put_object(f'{TICKET_PREFIX}{ticket_id}.txt', content.encode('utf-8'))

        status_data = {
            'id': ticket_id,
            'password': password,
            'password_hash': password_hash,
            'num1': a,
            'num2': b,
            'allowed_scene': allowed_scene,
            'created_at': datetime.now().isoformat(),
            'valid_date': valid_date,
            'expire_at': expire_timestamp,
            'used_count': 0,
            'records': [],
            'created_by': current_user.get('phone', 'unknown')
        }
        bucket.put_object(status_key, json.dumps(status_data, ensure_ascii=False).encode('utf-8'))

        results.append({
            'id': ticket_id,
            'password': password,
            'num1': a,
            'num2': b,
            'valid_date': valid_date,
            'allowed_scene': allowed_scene
        })

    ticket_ids = ','.join([r['id'] for r in results])
    log_operation(current_user['phone'], 'generate_ticket', ticket_ids,
                  f'入园{n1}人,观光车{n2}人,场景:{allowed_scene},共{len(results)}段')

    return jsonify({
        'segments': results,
        'total_n1': n1,
        'total_n2': n2,
        'message': f'生成 {len(results)} 个门票'
    })


@app.route('/api/ticket/verify', methods=['POST'])
@require_auth
@limiter.limit("20 per minute")
def verify_ticket():
    current_user = request.current_user
    data = request.json or {}
    ticket_id = data.get('id', '').strip()
    password = data.get('password', '').strip()
    scene = data.get('scene', '').strip()

    if not ticket_id:
        return jsonify({'error': '缺少门票编号'}), 400
    if not password:
        return jsonify({'error': '缺少密码'}), 400
    if scene not in ['入园', '观光车单程', '观光车往返']:
        return jsonify({'error': '场景无效'}), 400

    bucket = get_oss_client()
    status_key = f'{TICKET_PREFIX}{ticket_id}_status.json'
    if not bucket.object_exists(status_key):
        return jsonify({'valid': False, 'error': '门票不存在'}), 404

    obj = bucket.get_object(status_key)
    status = json.loads(obj.read().decode('utf-8'))

    allowed = status.get('allowed_scene', '通用')
    if allowed != '通用' and allowed != scene:
        return jsonify({'valid': False, 'error': f'该门票仅限"{allowed}"使用'}), 403

    expire_at = status.get('expire_at')
    if expire_at and int(time.time() * 1000) > expire_at:
        return jsonify({'valid': False, 'error': '门票已过期'}), 403

    stored_password = status.get('password')
    stored_hash = status.get('password_hash')
    input_hash = hash_password(password)

    if stored_password is not None:
        if stored_password != password:
            return jsonify({'valid': False, 'error': '密码错误'}), 403
    elif stored_hash:
        if stored_hash != input_hash:
            return jsonify({'valid': False, 'error': '密码错误'}), 403

    num1 = status.get('num1', 0)
    num2 = status.get('num2', 0)

    status['used_count'] += 1
    status['records'].append({
        'scene': scene,
        'time': datetime.now().isoformat(),
        'verified_by': current_user.get('phone', 'unknown')
    })
    bucket.put_object(status_key, json.dumps(status, ensure_ascii=False).encode('utf-8'))

    entry_count = sum(1 for r in status['records'] if r['scene'] == '入园')
    transport_count = sum(1 for r in status['records'] if r['scene'] in ['观光车', '观光车单程', '观光车往返'])

    log_operation(current_user['phone'], 'verify_ticket', ticket_id, f'场景:{scene}')

    return jsonify({
        'valid': True,
        'id': ticket_id,
        'num1': num1,
        'num2': num2,
        'used_count': status['used_count'],
        'entry_count': entry_count,
        'transport_count': transport_count,
        'scene': scene,
        'message': f'✅ {scene}核销成功！(入园{num1}人，观光车{num2}人)'
    })


@app.route('/api/ticket/list', methods=['GET'])
@require_auth
def list_tickets():
    bucket = get_oss_client()
    try:
        result = []
        marker = ''
        while True:
            resp = bucket.list_objects(prefix=TICKET_PREFIX, marker=marker, delimiter='/')
            for obj in resp.object_list:
                if obj.key.endswith('_status.json'):
                    try:
                        o = bucket.get_object(obj.key)
                        s = json.loads(o.read().decode('utf-8'))
                        result.append({
                            'id': s.get('id', ''),
                            'num1': s.get('num1', 0),
                            'num2': s.get('num2', 0),
                            'allowed_scene': s.get('allowed_scene', '通用'),
                            'valid_date': s.get('valid_date', ''),
                            'created_at': s.get('created_at', ''),
                            'used_count': s.get('used_count', 0),
                            'created_by': s.get('created_by', '')
                        })
                    except Exception as e:
                        print(f'读取 {obj.key} 失败: {e}')
            if not resp.is_truncated:
                break
            marker = resp.next_marker
        return jsonify({'tickets': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ticket/search', methods=['POST'])
@require_auth
def search_ticket():
    current_user = request.current_user
    data = request.json or {}
    ticket_id = data.get('id', '').strip()
    password = data.get('password', '').strip()

    if not ticket_id:
        return jsonify({'error': '缺少门票编号'}), 400
    if not password:
        return jsonify({'error': '请输入当前登录密码'}), 400

    users = get_users()
    user = next((u for u in users if u['phone'] == current_user['phone']), None)
    if not user or user.get('password_hash') != hash_password(password):
        return jsonify({'error': '密码错误'}), 403

    bucket = get_oss_client()
    status_key = f'{TICKET_PREFIX}{ticket_id}_status.json'
    if not bucket.object_exists(status_key):
        return jsonify({'error': '门票不存在'}), 404

    obj = bucket.get_object(status_key)
    s = json.loads(obj.read().decode('utf-8'))

    log_operation(current_user['phone'], 'search_ticket', ticket_id, '')

    return jsonify({
        'id': s.get('id'),
        'password': s.get('password', '----'),
        'num1': s.get('num1', 0),
        'num2': s.get('num2', 0),
        'allowed_scene': s.get('allowed_scene', '通用'),
        'valid_date': s.get('valid_date', ''),
        'created_at': s.get('created_at', ''),
        'used_count': s.get('used_count', 0),
        'created_by': s.get('created_by', '')
    })


@app.route('/api/ticket/delete', methods=['DELETE'])
@require_admin
def delete_ticket():
    current_user = request.current_user
    data = request.json or {}
    ticket_id = data.get('id', '').strip()
    if not ticket_id:
        return jsonify({'error': '缺少门票编号'}), 400

    bucket = get_oss_client()
    files = [
        f'{TICKET_PREFIX}{ticket_id}.txt',
        f'{TICKET_PREFIX}{ticket_id}_status.json'
    ]
    deleted = []
    for key in files:
        if bucket.object_exists(key):
            bucket.delete_object(key)
            deleted.append(key)

    if not deleted:
        return jsonify({'error': '门票不存在'}), 404

    log_operation(current_user['phone'], 'delete_ticket', ticket_id, '')
    return jsonify({'message': f'已删除门票 {ticket_id}'})


@app.route('/api/ticket/status', methods=['GET'])
@require_auth
def get_ticket_status():
    ticket_id = request.args.get('id', '').strip()
    if not ticket_id:
        return jsonify({'error': '缺少门票编号'}), 400

    bucket = get_oss_client()
    status_key = f'{TICKET_PREFIX}{ticket_id}_status.json'
    if not bucket.object_exists(status_key):
        return jsonify({'exists': False})

    obj = bucket.get_object(status_key)
    s = json.loads(obj.read().decode('utf-8'))

    entry_count = sum(1 for r in s['records'] if r['scene'] == '入园')
    transport_count = sum(1 for r in s['records'] if r['scene'] in ['观光车', '观光车单程', '观光车往返'])

    return jsonify({
        'exists': True,
        'id': s['id'],
        'num1': s.get('num1', 0),
        'num2': s.get('num2', 0),
        'allowed_scene': s.get('allowed_scene', '通用'),
        'valid_date': s.get('valid_date', ''),
        'created_at': s['created_at'],
        'used_count': s['used_count'],
        'entry_count': entry_count,
        'transport_count': transport_count,
        'created_by': s.get('created_by', ''),
        'records': s['records']
    })


@app.route('/api/ticket/reset', methods=['POST'])
@require_admin
def reset_ticket():
    current_user = request.current_user
    data = request.json or {}
    ticket_id = data.get('id', '').strip()
    if not ticket_id:
        return jsonify({'error': '缺少门票编号'}), 400

    bucket = get_oss_client()
    status_key = f'{TICKET_PREFIX}{ticket_id}_status.json'
    if not bucket.object_exists(status_key):
        return jsonify({'error': '门票不存在'}), 404

    obj = bucket.get_object(status_key)
    s = json.loads(obj.read().decode('utf-8'))
    s['used_count'] = 0
    s['records'] = []
    bucket.put_object(status_key, json.dumps(s, ensure_ascii=False).encode('utf-8'))

    log_operation(current_user['phone'], 'reset_ticket', ticket_id, '')
    return jsonify({'message': '核销状态已重置'})


# ---------- 根路由 ----------
@app.route('/')
def index():
    try:
        return send_from_directory(PARENT_DIR, 'jingqu.html')
    except Exception as e:
        return f"无法加载页面：{e}", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)