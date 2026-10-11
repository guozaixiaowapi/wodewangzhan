# -*- coding: utf-8 -*-
import os
import json
import time
import random
import re
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import oss2

from alibabacloud_dysmsapi20170525.client import Client as SmsClient
from alibabacloud_dysmsapi20170525 import models as sms_models
from alibabacloud_tea_openapi import models as open_api_models

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

OSS_ACCESS_KEY_ID = config['OSS_ACCESS_KEY_ID']
OSS_ACCESS_KEY_SECRET = config['OSS_ACCESS_KEY_SECRET']
REGION = config.get('REGION', 'cn-chengdu')
BUCKET_NAME = 'aliyun-wangzhan1'

SENSITIVE_PREFIX = 'minganxinxi/'
LOG_PREFIX = 'rizhi/sms/'

# 验证码内存存储
sms_codes = {}


# ---------- OSS ----------
def get_oss_client():
    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f'http://oss-{REGION}.aliyuncs.com', BUCKET_NAME)


def read_oss_text(key):
    bucket = get_oss_client()
    try:
        obj = bucket.get_object(key)
        return obj.read().decode('utf-8').strip()
    except oss2.exceptions.NoSuchKey:
        return None


def write_oss_text(key, content):
    bucket = get_oss_client()
    bucket.put_object(key, content.encode('utf-8'))


# ---------- 读取敏感信息 ----------
def load_sms_config():
    return {
        'sign_name': read_oss_text(SENSITIVE_PREFIX + 'sign_name.txt'),
        'access_key_id': read_oss_text(SENSITIVE_PREFIX + 'access_key_id.txt'),
        'access_key_secret': read_oss_text(SENSITIVE_PREFIX + 'access_key_secret.txt'),
        'template_login': read_oss_text(SENSITIVE_PREFIX + 'template_login.txt'),
        'template_change_phone': read_oss_text(SENSITIVE_PREFIX + 'template_change_phone.txt'),
        'template_forgot_pwd': read_oss_text(SENSITIVE_PREFIX + 'template_forgot_pwd.txt'),
    }


def get_template_code(sms_config, purpose):
    if purpose == 'login':
        return sms_config.get('template_login')
    elif purpose == 'change_phone':
        return sms_config.get('template_change_phone')
    elif purpose == 'forgot':
        return sms_config.get('template_forgot_pwd')
    return None


# ---------- 日志 ----------
def log_sms(phone, operation, details=''):
    try:
        bucket = get_oss_client()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ip = request.remote_addr if request else 'unknown'
        line = f"{ts} | {phone} | {ip} | {operation} | {details}\n"
        key = f'{LOG_PREFIX}{phone}.txt'
        try:
            obj = bucket.get_object(key)
            existing = obj.read().decode('utf-8')
            new_content = existing + line
        except oss2.exceptions.NoSuchKey:
            new_content = line
        bucket.put_object(key, new_content.encode('utf-8'))
    except Exception as e:
        print(f'短信日志写入失败: {e}')


# ---------- 短信客户端 ----------
def get_sms_client(sms_config):
    cfg = open_api_models.Config(
        access_key_id=sms_config['access_key_id'],
        access_key_secret=sms_config['access_key_secret']
    )
    cfg.endpoint = 'dysmsapi.aliyuncs.com'
    return SmsClient(cfg)


# ---------- 发送验证码 ----------
@app.route('/api/sms/send', methods=['POST'])
def sms_send():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    purpose = data.get('purpose', 'login')

    if not re.match(r'^\d{11}$', phone):
        return jsonify({'error': '手机号格式错误'}), 400

    if purpose not in ['login', 'change_phone', 'forgot']:
        return jsonify({'error': '用途无效'}), 400

    # 60 秒内不能重复发送
    old = sms_codes.get(phone)
    if old and time.time() - old.get('sent_at', 0) < 60:
        return jsonify({'error': '请 60 秒后再试'}), 429

    # 每天最多 10 次
    today_key = f"count_{phone}_{datetime.now().strftime('%Y%m%d')}"
    today_count = sms_codes.get(today_key, 0)
    if today_count >= 10:
        return jsonify({'error': '今日发送次数已达上限'}), 429

    sms_config = load_sms_config()
    if not sms_config['sign_name'] or not sms_config['access_key_id']:
        return jsonify({'error': '短信服务未配置'}), 500

    template_code = get_template_code(sms_config, purpose)
    if not template_code:
        return jsonify({'error': f'模板未配置：{purpose}'}), 500

    code = str(random.randint(100000, 999999))

    try:
        client = get_sms_client(sms_config)
        req = sms_models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=sms_config['sign_name'],
            template_code=template_code,
            template_param=json.dumps({'code': code})
        )
        resp = client.send_sms(req)
        if resp.body.code != 'OK':
            log_sms(phone, 'send_fail', f'{purpose} | {resp.body.message}')
            return jsonify({'error': resp.body.message}), 500
    except Exception as e:
        log_sms(phone, 'send_error', f'{purpose} | {e}')
        return jsonify({'error': f'发送失败：{e}'}), 500

    sms_codes[phone] = {
        'code': code,
        'expire': time.time() + 300,
        'sent_at': time.time(),
        'purpose': purpose
    }
    sms_codes[today_key] = today_count + 1

    log_sms(phone, 'send_ok', f'{purpose}')
    return jsonify({'message': '验证码已发送'})


# ---------- 验证验证码 ----------
@app.route('/api/sms/verify', methods=['POST'])
def sms_verify():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    purpose = data.get('purpose', 'login')

    if not phone or not code:
        return jsonify({'error': '缺少参数'}), 400

    record = sms_codes.get(phone)
    if not record:
        return jsonify({'error': '请先获取验证码'}), 400
    if time.time() > record['expire']:
        sms_codes.pop(phone, None)
        return jsonify({'error': '验证码已过期'}), 400
    if record['code'] != code:
        log_sms(phone, 'verify_fail', f'{purpose} | 错误码')
        return jsonify({'error': '验证码错误'}), 400
    if record['purpose'] != purpose:
        return jsonify({'error': '用途不匹配'}), 400

    sms_codes.pop(phone, None)
    log_sms(phone, 'verify_ok', f'{purpose}')
    return jsonify({'valid': True})


# ---------- 健康检查 ----------
@app.route('/api/sms/health', methods=['GET'])
def health():
    sms_config = load_sms_config()
    return jsonify({
        'status': 'ok',
        'sign_configured': bool(sms_config['sign_name']),
        'templates': {
            'login': bool(sms_config['template_login']),
            'change_phone': bool(sms_config['template_change_phone']),
            'forgot': bool(sms_config['template_forgot_pwd'])
        }
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)