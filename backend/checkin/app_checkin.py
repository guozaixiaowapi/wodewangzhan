# -*- coding: utf-8 -*-
import os
import json
import time
import hashlib
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

OSS_PREFIX = 'qiandaozhongxin/'
LOG_SUB = 'rizhi/'

DATA_FILE = OSS_PREFIX + 'data.json'

DEFAULT_DATA = {
    'users': [
        {
            'phone': '18981820927',
            'password': 'guoguo2015',
            'role': 'master',
            'name': '主控',
            'familyId': None
        },
        {
            'phone': '19182020561',
            'password': 'guoguo2015',
            'role': 'deputy',
            'name': '副控',
            'familyId': None
        }
    ],
    'families': [],
    'activities': [],
    'records': []
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


# ---------- 日志 ----------
def log_operation(phone, operation, details=''):
    try:
        bucket = get_oss_client()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{ts} | {operation} | {details}\n"
        key = f'{OSS_PREFIX}{phone}/{LOG_SUB}{phone}.txt'
        try:
            obj = bucket.get_object(key)
            existing = obj.read().decode('utf-8')
            new_content = existing + line
        except oss2.exceptions.NoSuchKey:
            new_content = line
        bucket.put_object(key, new_content.encode('utf-8'))
    except Exception as e:
        print(f'签到日志写入失败: {e}')


# ---------- 数据读写 ----------
def load_data():
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(DATA_FILE)
        data = json.loads(obj.read().decode('utf-8'))
        # 兼容旧数据
        for k in ['users', 'families', 'activities', 'records']:
            if k not in data:
                data[k] = []
        return data
    except oss2.exceptions.NoSuchKey:
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    bucket = get_oss_client()
    bucket.put_object(DATA_FILE, json.dumps(data, ensure_ascii=False).encode('utf-8'))


# ---------- SSO（从主界面进来） ----------
@app.route('/api/auth/sso', methods=['POST'])
def sso_login():
    """主界面带手机号过来，自动授权"""
    data = request.json or {}
    phone = data.get('phone', '').strip()
    name = data.get('name', '').strip()

    if not phone:
        return jsonify({'error': '缺少手机号'}), 400

    app_data = load_data()
    user = next((u for u in app_data['users'] if u['phone'] == phone), None)

    if not user:
        # 自动创建，默认是签到游客
        user = {
            'phone': phone,
            'password': '123456',
            'role': 'guest',
            'name': name or phone,
            'familyId': None
        }
        app_data['users'].append(user)
        save_data(app_data)
        log_operation(phone, 'sso_register', f'新用户:{user["name"]}')

    token = generate_jwt(user)
    log_operation(phone, 'sso_login', f'角色:{user["role"]}')

    return jsonify({
        'token': token,
        'user': user
    })


# ---------- 密码登录（备用） ----------
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()

    if not phone or not password:
        return jsonify({'error': '请输入账号和密码'}), 400

    app_data = load_data()
    user = next((u for u in app_data['users'] if u['phone'] == phone), None)
    if not user:
        return jsonify({'error': '账号不存在'}), 401
    if user.get('password') != password:
        return jsonify({'error': '密码错误'}), 401

    # 检查临时账号是否过期
    if user.get('role') == 'temp' and user.get('expireTime'):
        if time.time() > user['expireTime']:
            return jsonify({'error': '临时账号已过期'}), 401

    token = generate_jwt(user)
    log_operation(phone, 'login', f'密码登录')
    return jsonify({'token': token, 'user': user})


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    app_data = load_data()
    user = next((u for u in app_data['users'] if u['phone'] == request.current_user['phone']), None)
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify({'user': user})


# ---------- 全部数据（读） ----------
@app.route('/api/data/get', methods=['GET'])
@require_auth
def data_get():
    app_data = load_data()
    # 隐藏密码
    users = [{k: v for k, v in u.items() if k != 'password'} for u in app_data['users']]
    return jsonify({
        'users': users,
        'families': app_data['families'],
        'activities': app_data['activities'],
        'records': app_data['records']
    })


# ---------- 全部数据（写） ----------
@app.route('/api/data/save', methods=['POST'])
@require_auth
def data_save():
    """前端把整个 appData 传上来，后端合并写回"""
    current = request.current_user
    if current['role'] not in ['master', 'deputy', 'familyMaster', 'deputyGuest']:
        return jsonify({'error': '权限不足'}), 403

    incoming = request.json or {}
    app_data = load_data()

    # 合并策略：以传入的数据为准（前端已经处理过合并逻辑）
    if 'users' in incoming:
        # 保留密码（前端不传密码，所以要合并回来）
        old_pw_map = {u['phone']: u.get('password') for u in app_data['users']}
        new_users = []
        for u in incoming['users']:
            if 'password' not in u or not u['password']:
                u['password'] = old_pw_map.get(u['phone'], '123456')
            new_users.append(u)
        # 保证原有用户不丢
        incoming_phones = {u['phone'] for u in new_users}
        for old_u in app_data['users']:
            if old_u['phone'] not in incoming_phones:
                new_users.append(old_u)
        app_data['users'] = new_users

    if 'families' in incoming:
        app_data['families'] = incoming['families']

    if 'activities' in incoming:
        app_data['activities'] = incoming['activities']

    if 'records' in incoming:
        # 记录按 id 去重合并
        old_ids = {r['id'] for r in app_data['records']}
        for r in incoming['records']:
            if r['id'] not in old_ids:
                app_data['records'].append(r)
                old_ids.add(r['id'])

    save_data(app_data)
    log_operation(current['phone'], 'save_data', f'用户:{len(app_data["users"])},家庭:{len(app_data["families"])},活动:{len(app_data["activities"])},记录:{len(app_data["records"])}')
    return jsonify({'message': '保存成功'})


# ---------- 添加签到记录（单独接口） ----------
@app.route('/api/records/add', methods=['POST'])
@require_auth
def records_add():
    current = request.current_user
    data = request.json or {}
    activity_id = data.get('activityId', '').strip()
    name = data.get('name', '').strip()

    if not activity_id or not name:
        return jsonify({'error': '缺少参数'}), 400

    app_data = load_data()
    activity = next((a for a in app_data['activities'] if a['id'] == activity_id), None)
    if not activity:
        return jsonify({'error': '签到活动不存在'}), 404
    if not activity.get('isActive'):
        return jsonify({'error': '该活动未激活'}), 400

    # 检查是否已签到
    already = any(
        r for r in app_data['records']
        if r['phone'] == current['phone'] and r['activityId'] == activity_id
    )
    if already:
        return jsonify({'error': '您已签到'}), 400

    record = {
        'id': 'r' + str(int(time.time() * 1000)) + os.urandom(2).hex(),
        'activityId': activity_id,
        'phone': current['phone'],
        'name': name,
        'timestamp': int(time.time() * 1000)
    }
    app_data['records'].append(record)
    save_data(app_data)

    log_operation(current['phone'], 'checkin', f'活动:{activity_id}, 姓名:{name}')

    return jsonify({'message': '签到成功', 'record': record})


# ---------- 添加签到活动 ----------
@app.route('/api/activities/add', methods=['POST'])
@require_auth
def activities_add():
    current = request.current_user
    if current['role'] not in ['master', 'deputy', 'familyMaster', 'deputyGuest']:
        return jsonify({'error': '权限不足'}), 403

    data = request.json or {}
    family_id = data.get('familyId', '').strip()
    name = data.get('name', '').strip()

    if not family_id or not name:
        return jsonify({'error': '缺少参数'}), 400

    app_data = load_data()
    family = next((f for f in app_data['families'] if f['id'] == family_id), None)
    if not family:
        return jsonify({'error': '家庭不存在'}), 404

    activity = {
        'id': 'act' + str(int(time.time() * 1000)),
        'familyId': family_id,
        'name': name,
        'isActive': False,
        'createdBy': current['phone'],
        'createdAt': int(time.time() * 1000)
    }
    app_data['activities'].append(activity)
    save_data(app_data)

    log_operation(current['phone'], 'add_activity', f'活动:{name}, 家庭:{family_id}')
    return jsonify({'message': '创建成功', 'activity': activity})


# ---------- 激活/停用签到活动 ----------
@app.route('/api/activities/toggle', methods=['POST'])
@require_auth
def activities_toggle():
    current = request.current_user
    if current['role'] not in ['master', 'deputy', 'familyMaster', 'deputyGuest']:
        return jsonify({'error': '权限不足'}), 403

    data = request.json or {}
    activity_id = data.get('id', '').strip()

    app_data = load_data()
    activity = next((a for a in app_data['activities'] if a['id'] == activity_id), None)
    if not activity:
        return jsonify({'error': '活动不存在'}), 404

    if activity.get('isActive'):
        activity['isActive'] = False
    else:
        # 先全部停用
        for a in app_data['activities']:
            a['isActive'] = False
        activity['isActive'] = True

    save_data(app_data)
    log_operation(current['phone'], 'toggle_activity', f'活动:{activity_id}, 状态:{activity["isActive"]}')
    return jsonify({'message': '操作成功', 'activity': activity})


# ---------- 添加家庭 ----------
@app.route('/api/families/add', methods=['POST'])
@require_auth
def families_add():
    current = request.current_user
    if current['role'] not in ['master', 'deputy']:
        return jsonify({'error': '权限不足'}), 403

    data = request.json or {}
    fid = data.get('id', '').strip()
    name = data.get('name', '').strip()
    invite = data.get('inviteCode', '').strip()

    if not fid or not name:
        return jsonify({'error': '缺少参数'}), 400

    app_data = load_data()
    if any(f['id'] == fid for f in app_data['families']):
        return jsonify({'error': '家庭号已存在'}), 400

    family = {
        'id': fid,
        'name': name,
        'inviteCode': invite,
        'createdBy': current['phone'],
        'createdAt': int(time.time() * 1000)
    }
    app_data['families'].append(family)
    save_data(app_data)

    log_operation(current['phone'], 'add_family', f'家庭:{name}, 家庭号:{fid}')
    return jsonify({'message': '创建成功', 'family': family})


# ---------- 添加用户 ----------
@app.route('/api/users/add', methods=['POST'])
@require_auth
def users_add():
    current = request.current_user
    if current['role'] not in ['master', 'deputy', 'familyMaster']:
        return jsonify({'error': '权限不足'}), 403

    data = request.json or {}
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    role = data.get('role', 'guest')
    family_id = data.get('familyId')

    if not phone or not password or not name:
        return jsonify({'error': '缺少参数'}), 400

    app_data = load_data()
    if any(u['phone'] == phone for u in app_data['users']):
        return jsonify({'error': '手机号已存在'}), 400

    user = {
        'phone': phone,
        'password': password,
        'name': name,
        'role': role,
        'familyId': family_id
    }
    app_data['users'].append(user)
    save_data(app_data)

    log_operation(current['phone'], 'add_user', f'用户:{name}, 角色:{role}')
    return jsonify({'message': '添加成功'})


# ---------- 删除用户 ----------
@app.route('/api/users/delete', methods=['POST'])
@require_auth
def users_delete():
    current = request.current_user
    data = request.json or {}
    phone = data.get('phone', '').strip()

    if phone == current['phone']:
        return jsonify({'error': '不能删除自己'}), 403
    if phone == '18981820927':
        return jsonify({'error': '不能删除主控'}), 403

    app_data = load_data()
    target = next((u for u in app_data['users'] if u['phone'] == phone), None)
    if not target:
        return jsonify({'error': '用户不存在'}), 404

    if current['role'] == 'deputy' and target['role'] in ['master', 'deputy']:
        return jsonify({'error': '权限不足'}), 403
    if current['role'] == 'familyMaster':
        if target.get('familyId') != current.get('familyId'):
            return jsonify({'error': '只能删除本家庭成员'}), 403

    app_data['users'] = [u for u in app_data['users'] if u['phone'] != phone]
    save_data(app_data)

    log_operation(current['phone'], 'delete_user', f'用户:{phone}')
    return jsonify({'message': '删除成功'})


# ---------- 健康检查 ----------
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5004, debug=False)