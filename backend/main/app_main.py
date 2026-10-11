# -*- coding: utf-8 -*-
import os
import json
import time
import secrets
import string
import uuid
import jwt
import re
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import oss2
import requests

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
SMS_SERVICE = config.get('SMS_SERVICE', 'http://127.0.0.1:5002')

OSS_PREFIX = 'zhujiemian/'
LOG_PREFIX = 'rizhi/'
CLOUD_PREFIX = 'yunkongjian/'
CACHE_PREFIX = 'huancun/'
DEFAULT_QUOTA = 2147483648  # 2GB

SUPER_ADMIN = {
    'phone': '18981820927',
    'password': 'guoguo2015',
    'role': 'super',
    'name': '超级管理员',
    'permissions': ['jingqu', 'checkin', 'game'],
    'member_authorized': True,
    'cloud_limit': 2147483648,
    'cloud_used': 0,
    'created_at': int(time.time())
}

# ---------- 工具 ----------
def get_oss_client():
    auth = oss2.Auth(ACCESS_KEY_ID, ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f'http://oss-{REGION}.aliyuncs.com', BUCKET_NAME)

def generate_jwt(user):
    payload = {
        'phone': user['phone'],
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
        if request.current_user.get('role') not in ['super', 'master', 'deputy']:
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

def gen_activation_code():
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(30))

# ---------- 数据文件 ----------
USERS_FILE = OSS_PREFIX + 'users.json'
ACTIVATIONS_FILE = OSS_PREFIX + 'activations.json'
CLOUD_USAGE_FILE = OSS_PREFIX + 'cloud_usage.json'

def load_users():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(USERS_FILE)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        users = [SUPER_ADMIN]
        save_users(users)
        return users

def save_users(users):
    bucket = get_oss_client()
    bucket.put_object(USERS_FILE, json.dumps(users, ensure_ascii=False).encode('utf-8'))

def load_activations():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(ACTIVATIONS_FILE)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        return []

def save_activations(acts):
    bucket = get_oss_client()
    bucket.put_object(ACTIVATIONS_FILE, json.dumps(acts, ensure_ascii=False).encode('utf-8'))

def load_cloud_usage():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(CLOUD_USAGE_FILE)
        return json.loads(obj.read().decode('utf-8'))
    except oss2.exceptions.NoSuchKey:
        return {}

def save_cloud_usage(usage):
    bucket = get_oss_client()
    bucket.put_object(CLOUD_USAGE_FILE, json.dumps(usage, ensure_ascii=False).encode('utf-8'))

def find_user(phone):
    users = load_users()
    return next((u for u in users if u['phone'] == phone), None)

def safe_user(user):
    if not user:
        return None
    return {k: v for k, v in user.items() if k != 'password'}

# ---------- 短信代理 ----------
@app.route('/api/sms/send', methods=['POST'])
def sms_send():
    data = request.json or {}
    try:
        resp = requests.post(f'{SMS_SERVICE}/api/sms/send', json=data, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'短信服务不可用：{e}'}), 500

# ---------- 登录（验证码） ----------
@app.route('/api/auth/login-sms', methods=['POST'])
def login_sms():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()

    if not re.match(r'^\d{11}$', phone):
        return jsonify({'error': '手机号格式错误'}), 400

    try:
        resp = requests.post(f'{SMS_SERVICE}/api/sms/verify',
                             json={'phone': phone, 'code': code, 'purpose': 'login'}, timeout=10)
        result = resp.json()
        if not resp.ok or not result.get('valid'):
            return jsonify({'error': result.get('error', '验证码错误')}), 400
    except Exception as e:
        return jsonify({'error': f'短信服务不可用：{e}'}), 500

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)

    is_new = False
    if not user:
        user = {
            'phone': phone,
            'password': None,
            'role': 'user',
            'name': '',
            'permissions': [],
            'member_authorized': False,
            'cloud_limit': 2147483648,
            'cloud_used': 0,
            'created_at': int(time.time())
        }
        users.append(user)
        save_users(users)
        is_new = True
        log_operation(phone, 'register', phone, '新用户注册')

    token = generate_jwt(user)
    log_operation(phone, 'login_sms', phone, '验证码登录')
    return jsonify({
        'token': token,
        'user': safe_user(user),
        'is_new': is_new,
        'need_password': not user.get('password')
    })

# ---------- 登录（密码） ----------
@app.route('/api/auth/login-pwd', methods=['POST'])
def login_pwd():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()

    if not phone or not password:
        return jsonify({'error': '请输入手机号和密码'}), 400

    user = find_user(phone)
    if not user:
        return jsonify({'error': '用户不存在'}), 401
    if not user.get('password'):
        return jsonify({'error': '请先用验证码登录并设置密码'}), 401
    if user['password'] != password:
        return jsonify({'error': '密码错误'}), 401

    token = generate_jwt(user)
    log_operation(phone, 'login_pwd', phone, '密码登录')
    return jsonify({'token': token, 'user': safe_user(user)})

# ---------- 当前用户 ----------
@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    user = find_user(request.current_user['phone'])
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': safe_user(user)})

# ---------- 设置密码 ----------
@app.route('/api/auth/set-password', methods=['POST'])
@require_auth
def set_password():
    data = request.json or {}
    password = data.get('password', '').strip()

    if len(password) < 8:
        return jsonify({'error': '密码至少 8 位'}), 400
    has_letter = bool(re.search(r'[a-zA-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_symbol = bool(re.search(r'[^a-zA-Z0-9]', password))
    if sum([has_letter, has_digit, has_symbol]) < 2:
        return jsonify({'error': '密码需包含字母、数字、符号中的至少两种'}), 400

    users = load_users()
    user = next((u for u in users if u['phone'] == request.current_user['phone']), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    user['password'] = password
    save_users(users)
    log_operation(user['phone'], 'set_password', user['phone'], '设置密码')
    return jsonify({'message': '密码设置成功'})

# ---------- 修改密码 ----------
@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data = request.json or {}
    old_pwd = data.get('old_password', '').strip()
    new_pwd = data.get('new_password', '').strip()

    users = load_users()
    user = next((u for u in users if u['phone'] == request.current_user['phone']), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if user.get('password') and user['password'] != old_pwd:
        return jsonify({'error': '旧密码错误'}), 401
    if len(new_pwd) < 8:
        return jsonify({'error': '密码至少 8 位'}), 400

    user['password'] = new_pwd
    save_users(users)
    log_operation(user['phone'], 'change_password', user['phone'], '')
    return jsonify({'message': '密码修改成功'})

# ---------- 忘记密码 ----------
@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    new_pwd = data.get('new_password', '').strip()

    if not re.match(r'^\d{11}$', phone):
        return jsonify({'error': '手机号格式错误'}), 400
    if len(new_pwd) < 8:
        return jsonify({'error': '密码至少 8 位'}), 400

    try:
        resp = requests.post(f'{SMS_SERVICE}/api/sms/verify',
                             json={'phone': phone, 'code': code, 'purpose': 'forgot'}, timeout=10)
        result = resp.json()
        if not resp.ok or not result.get('valid'):
            return jsonify({'error': result.get('error', '验证码错误')}), 400
    except Exception as e:
        return jsonify({'error': f'短信服务不可用：{e}'}), 500

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    user['password'] = new_pwd
    save_users(users)
    log_operation(phone, 'forgot_password', phone, '重置密码')
    return jsonify({'message': '密码重置成功'})

# ---------- 换绑手机号 ----------
@app.route('/api/auth/change-phone', methods=['POST'])
@require_auth
def change_phone():
    data = request.json or {}
    new_phone = data.get('new_phone', '').strip()
    code = data.get('code', '').strip()

    if not re.match(r'^\d{11}$', new_phone):
        return jsonify({'error': '手机号格式错误'}), 400

    try:
        resp = requests.post(f'{SMS_SERVICE}/api/sms/verify',
                             json={'phone': new_phone, 'code': code, 'purpose': 'change_phone'}, timeout=10)
        result = resp.json()
        if not resp.ok or not result.get('valid'):
            return jsonify({'error': result.get('error', '验证码错误')}), 400
    except Exception as e:
        return jsonify({'error': f'短信服务不可用：{e}'}), 500

    users = load_users()
    if any(u['phone'] == new_phone for u in users):
        return jsonify({'error': '该手机号已被使用'}), 400

    old_phone = request.current_user['phone']
    user = next((u for u in users if u['phone'] == old_phone), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    user['phone'] = new_phone
    save_users(users)
    log_operation(new_phone, 'change_phone', f'{old_phone} -> {new_phone}', '')
    return jsonify({'message': '换绑成功', 'new_phone': new_phone})

# ---------- 用户列表 ----------
@app.route('/api/users/list', methods=['GET'])
@require_admin
def list_users():
    role = request.current_user.get('role')
    users = load_users()
    if role in ['master', 'deputy']:
        pass
    safe = [safe_user(u) for u in users]
    return jsonify({'users': safe})

# ---------- 创建用户 ----------
@app.route('/api/users/create', methods=['POST'])
@require_admin
def create_user():
    current = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()
    role = data.get('role', 'user')
    name = data.get('name', '').strip()

    if not re.match(r'^\d{11}$', phone):
        return jsonify({'error': '手机号格式错误'}), 400
    if role not in ['master', 'deputy', 'user']:
        return jsonify({'error': '角色无效'}), 400

    users = load_users()
    if any(u['phone'] == phone for u in users):
        return jsonify({'error': '手机号已存在'}), 400

    if role == 'master' and sum(1 for u in users if u['role'] == 'master') >= 5:
        return jsonify({'error': '主管理已达上限（5）'}), 400
    if role == 'deputy' and sum(1 for u in users if u['role'] == 'deputy') >= 10:
        return jsonify({'error': '副管理已达上限（10）'}), 400

    if current['role'] != 'super':
        return jsonify({'error': '只有超级管理员能创建主/副管理'}), 403

    users.append({
        'phone': phone,
        'password': None,
        'role': role,
        'name': name,
        'permissions': [],
        'member_authorized': False,
        'cloud_limit': 2147483648,
        'cloud_used': 0,
        'created_at': int(time.time())
    })
    save_users(users)
    log_operation(current['phone'], 'create_user', phone, f'角色:{role}')
    return jsonify({'message': '创建成功'})

# ---------- 修改用户权限 ----------
@app.route('/api/users/permissions', methods=['POST'])
@require_admin
def update_permissions():
    current = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()
    permissions = data.get('permissions', [])

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    if current['role'] == 'master' and user['role'] == 'master':
        return jsonify({'error': '不能修改其他主管理'}), 403
    if current['role'] == 'deputy' and user['role'] in ['master', 'deputy']:
        return jsonify({'error': '副管理不能修改主/副管理'}), 403

    user['permissions'] = permissions
    save_users(users)
    log_operation(current['phone'], 'update_permissions', phone, f'权限:{permissions}')
    return jsonify({'message': '权限更新成功'})

# ---------- 会员中心授权 ----------
@app.route('/api/users/member-auth', methods=['POST'])
@require_auth
def member_auth():
    current = request.current_user
    if current['role'] != 'super':
        return jsonify({'error': '只有超级管理员能授权'}), 403
    data = request.json or {}
    phone = data.get('phone', '').strip()
    authorized = bool(data.get('authorized', True))

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    user['member_authorized'] = authorized
    save_users(users)
    log_operation(current['phone'], 'member_auth', phone, f'会员中心授权:{authorized}')
    return jsonify({'message': '授权成功'})

# ---------- 删除用户 ----------
@app.route('/api/users/delete', methods=['POST'])
@require_admin
def delete_user():
    current = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()

    if phone == current['phone']:
        return jsonify({'error': '不能删除自己'}), 403
    if phone == SUPER_ADMIN['phone']:
        return jsonify({'error': '不能删除超级管理员'}), 403

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    if user['role'] == 'master' and current['role'] != 'super':
        return jsonify({'error': '只有超级管理员能删除主管理'}), 403
    if user['role'] == 'deputy' and current['role'] not in ['super', 'master']:
        return jsonify({'error': '权限不足'}), 403

    users = [u for u in users if u['phone'] != phone]
    save_users(users)
    log_operation(current['phone'], 'delete_user', phone, '')
    return jsonify({'message': '删除成功'})

# ---------- 激活码 ----------
@app.route('/api/activation/create', methods=['POST'])
@require_admin
def activation_create():
    current = request.current_user
    data = request.json or {}
    atype = data.get('type')

    if atype not in ['permission', 'cloud', 'admin']:
        return jsonify({'error': '类型错误'}), 400

    code = gen_activation_code()
    acts = load_activations()
    while any(a['code'] == code for a in acts):
        code = gen_activation_code()

    act = {
        'code': code,
        'type': atype,
        'created_by': current['phone'],
        'created_at': int(time.time()),
        'used_by': None,
        'used_at': None
    }

    if atype == 'permission':
        perms = data.get('permissions', [])
        if not perms:
            return jsonify({'error': '请至少选择一个模块'}), 400
        act['permissions'] = perms
    elif atype == 'cloud':
        gb = int(data.get('cloud_gb', 0) or 0)
        if gb <= 0:
            return jsonify({'error': '请输入有效容量'}), 400
        act['cloud_bytes'] = gb * 1073741824
    elif atype == 'admin':
        role = data.get('admin_role', 'deputy')
        if role not in ['master', 'deputy']:
            return jsonify({'error': '角色无效'}), 400
        users = load_users()
        if role == 'master' and sum(1 for u in users if u['role'] == 'master') >= 5:
            return jsonify({'error': '主管理已达上限'}), 400
        if role == 'deputy' and sum(1 for u in users if u['role'] == 'deputy') >= 10:
            return jsonify({'error': '副管理已达上限'}), 400
        act['admin_role'] = role

    acts.append(act)
    save_activations(acts)
    log_operation(current['phone'], 'create_activation', code, f'类型:{atype}')
    return jsonify({'code': code})

@app.route('/api/activation/use', methods=['POST'])
@require_auth
def activation_use():
    current = request.current_user
    data = request.json or {}
    code = data.get('code', '').strip()

    acts = load_activations()
    act = next((a for a in acts if a['code'] == code), None)
    if not act:
        return jsonify({'error': '激活码无效'}), 404
    if act.get('used_by'):
        return jsonify({'error': '激活码已被使用'}), 400

    users = load_users()
    user = next((u for u in users if u['phone'] == current['phone']), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    if act['type'] == 'permission':
        perms = set(user.get('permissions', []))
        perms.update(act.get('permissions', []))
        user['permissions'] = list(perms)
    elif act['type'] == 'cloud':
        user['cloud_limit'] = user.get('cloud_limit', 2147483648) + act.get('cloud_bytes', 0)
    elif act['type'] == 'admin':
        role = act.get('admin_role', 'deputy')
        if role == 'master' and sum(1 for u in users if u['role'] == 'master') >= 5:
            return jsonify({'error': '主管理已达上限，无法激活'}), 400
        if role == 'deputy' and sum(1 for u in users if u['role'] == 'deputy') >= 10:
            return jsonify({'error': '副管理已达上限，无法激活'}), 400
        user['role'] = role

    act['used_by'] = current['phone']
    act['used_at'] = int(time.time())
    save_users(users)
    save_activations(acts)
    log_operation(current['phone'], 'use_activation', code, f'类型:{act["type"]}')
    return jsonify({'user': safe_user(user)})

# ---------- 注销 ----------
@app.route('/api/auth/delete-account', methods=['POST'])
@require_auth
def delete_account():
    phone = request.current_user['phone']
    if phone == SUPER_ADMIN['phone']:
        return jsonify({'error': '超级管理员不能注销'}), 403

    users = load_users()
    users = [u for u in users if u['phone'] != phone]
    save_users(users)
    log_operation(phone, 'delete_account', phone, '注销账号')
    return jsonify({'message': '账号已注销'})

# ============ 云空间 ============

def get_user_cloud(phone):
    """获取用户云空间信息"""
    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if not user:
        return None
    if 'cloud_limit' not in user:
        user['cloud_limit'] = DEFAULT_QUOTA
    if 'cloud_used' not in user:
        user['cloud_used'] = 0
    return user


def recalc_cloud_used(phone):
    """重新从 OSS 算用户已用大小"""
    bucket = get_oss_client()
    prefix = f'{CLOUD_PREFIX}{phone}/'
    total = 0
    marker = ''
    while True:
        resp = bucket.list_objects(prefix=prefix, marker=marker)
        for obj in resp.object_list:
            total += obj.size
        if not resp.is_truncated:
            break
        marker = resp.next_marker
    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if user:
        user['cloud_used'] = total
        save_users(users)
    return total


@app.route('/api/cloud/info', methods=['GET'])
@require_auth
def cloud_info():
    user = find_user(request.current_user['phone'])
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({
        'limit': user.get('cloud_limit', DEFAULT_QUOTA),
        'used': user.get('cloud_used', 0)
    })


@app.route('/api/cloud/upload', methods=['POST'])
@require_auth
def cloud_upload():
    """上传：huancun/{临时ID}/ → yunkongjian/{手机号}/ → 删缓存"""
    phone = request.current_user['phone']
    user = get_user_cloud(phone)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    if 'file' not in request.files:
        return jsonify({'error': '缺少文件'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': '文件名为空'}), 400

    temp_id = request.form.get('temp_id', '').strip()
    if not temp_id:
        temp_id = uuid.uuid4().hex

    original_name = file.filename
    safe_name = original_name.replace('/', '_').replace('\\', '_')

    file_data = file.read()
    file_size = len(file_data)

    limit = user.get('cloud_limit', DEFAULT_QUOTA)
    used = user.get('cloud_used', 0)
    if used + file_size > limit:
        return jsonify({
            'error': f'空间不足，已用 {used/1048576:.2f}MB，限额 {limit/1048576:.2f}MB，本次 {file_size/1048576:.2f}MB'
        }), 400

    bucket = get_oss_client()

    cache_key = f'{CACHE_PREFIX}{temp_id}/{safe_name}'
    try:
        bucket.put_object(cache_key, file_data)
    except Exception as e:
        return jsonify({'error': f'缓存写入失败：{e}'}), 500

    target_key = f'{CLOUD_PREFIX}{phone}/{safe_name}'
    try:
        bucket.put_object(target_key, file_data)
    except Exception as e:
        return jsonify({'error': f'转存失败：{e}'}), 500

    try:
        bucket.delete_object(cache_key)
    except Exception as e:
        print(f'缓存删除失败（不影响主流程）: {e}')

    users = load_users()
    target_user = next((u for u in users if u['phone'] == phone), None)
    if target_user:
        target_user['cloud_used'] = target_user.get('cloud_used', 0) + file_size
        save_users(users)

    log_operation(phone, 'cloud_upload', safe_name, f'大小:{file_size}字节')

    return jsonify({
        'message': '上传成功',
        'file': {
            'name': safe_name,
            'size': file_size,
            'key': target_key
        },
        'cloud_used': target_user.get('cloud_used', 0),
        'cloud_limit': target_user.get('cloud_limit', DEFAULT_QUOTA)
    })


@app.route('/api/cloud/list', methods=['GET'])
@require_auth
def cloud_list():
    """列出当前用户云空间所有文件"""
    phone = request.current_user['phone']
    bucket = get_oss_client()
    prefix = f'{CLOUD_PREFIX}{phone}/'

    files = []
    marker = ''
    while True:
        resp = bucket.list_objects(prefix=prefix, marker=marker)
        for obj in resp.object_list:
            files.append({
                'name': obj.key[len(prefix):],
                'size': obj.size,
                'last_modified': obj.last_modified,
                'key': obj.key
            })
        if not resp.is_truncated:
            break
        marker = resp.next_marker

    user = find_user(phone)
    return jsonify({
        'files': files,
        'cloud_used': user.get('cloud_used', 0) if user else 0,
        'cloud_limit': user.get('cloud_limit', DEFAULT_QUOTA) if user else DEFAULT_QUOTA
    })


@app.route('/api/cloud/download/<path:filename>', methods=['GET'])
@require_auth
def cloud_download(filename):
    """下载文件"""
    phone = request.current_user['phone']
    safe_name = filename.replace('/', '_').replace('\\', '_')
    key = f'{CLOUD_PREFIX}{phone}/{safe_name}'
    bucket = get_oss_client()

    try:
        obj = bucket.get_object(key)
        data = obj.read()
    except oss2.exceptions.NoSuchKey:
        return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'error': f'下载失败：{e}'}), 500

    from io import BytesIO
    bio = BytesIO(data)
    bio.seek(0)
    log_operation(phone, 'cloud_download', safe_name, '')
    return send_file(
        bio,
        as_attachment=True,
        download_name=safe_name
    )


@app.route('/api/cloud/delete', methods=['POST'])
@require_auth
def cloud_delete():
    """删除文件"""
    phone = request.current_user['phone']
    data = request.json or {}
    filename = data.get('filename', '').strip()
    if not filename:
        return jsonify({'error': '缺少文件名'}), 400

    safe_name = filename.replace('/', '_').replace('\\', '_')
    key = f'{CLOUD_PREFIX}{phone}/{safe_name}'
    bucket = get_oss_client()

    if not bucket.object_exists(key):
        return jsonify({'error': '文件不存在'}), 404

    try:
        obj = bucket.get_object(key)
        file_size = obj.content_length
        bucket.delete_object(key)
    except Exception as e:
        return jsonify({'error': f'删除失败：{e}'}), 500

    users = load_users()
    user = next((u for u in users if u['phone'] == phone), None)
    if user:
        user['cloud_used'] = max(0, user.get('cloud_used', 0) - file_size)
        save_users(users)

    log_operation(phone, 'cloud_delete', safe_name, '')
    return jsonify({'message': '删除成功', 'cloud_used': user.get('cloud_used', 0) if user else 0})


@app.route('/api/cloud/share', methods=['POST'])
@require_auth
def cloud_share():
    """生成分享链接（带 token 的临时链接）"""
    phone = request.current_user['phone']
    data = request.json or {}
    filename = data.get('filename', '').strip()
    expire_days = int(data.get('expire_days', 7) or 7)

    if not filename:
        return jsonify({'error': '缺少文件名'}), 400

    safe_name = filename.replace('/', '_').replace('\\', '_')
    key = f'{CLOUD_PREFIX}{phone}/{safe_name}'
    bucket = get_oss_client()

    if not bucket.object_exists(key):
        return jsonify({'error': '文件不存在'}), 404

    expire_seconds = expire_days * 86400
    try:
        url = bucket.sign_url('GET', key, expire_seconds, slash_safe=True)
    except Exception as e:
        return jsonify({'error': f'生成分享链接失败：{e}'}), 500

    log_operation(phone, 'cloud_share', safe_name, f'有效期:{expire_days}天')
    return jsonify({
        'url': url,
        'filename': safe_name,
        'expire_days': expire_days
    })


@app.route('/api/cloud/recalc', methods=['POST'])
@require_auth
def cloud_recalc():
    """重新计算已用空间"""
    phone = request.current_user['phone']
    total = recalc_cloud_used(phone)
    return jsonify({'cloud_used': total})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)