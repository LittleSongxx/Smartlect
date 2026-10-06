#!/usr/bin/env python3
"""向 Nacos 配置中心推送/更新 dataId（bootstrap 后执行，幂等覆盖）。

用法：
  python3 scripts/nacos_config_push.py                    # 推送全部公共+服务配置
  python3 scripts/nacos_config_push.py smartlect-product   # 仅推送指定服务

配置源：
  公共段 = backend/smartlect-common/src/main/resources/smartlect-common.yml
  服务段 = backend/{service}/app/src/main/resources/application.yml（去掉公共覆盖部分）

Nacos OpenAPI v1：POST /nacos/v1/cs/configs（登录 accessToken 鉴权）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'assistant' / 'src'))

ENV_FILE = ROOT / 'run' / 'runtime.env'
COMMON_YML = ROOT / 'backend/smartlect-common/src/main/resources/smartlect-common.yml'
SERVICES = ['smartlect-gateway', 'smartlect-admin', 'smartlect-user', 'smartlect-product',
            'smartlect-stock', 'smartlect-cart', 'smartlect-order', 'smartlect-pay',
            'smartlect-coupon']
GROUP = 'SMARTLECT_GROUP'


def load_env():
    import os
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def nacos_login():
    import urllib.request
    import urllib.parse
    import json
    import os
    base = f"http://127.0.0.1:{os.environ.get('SMARTLECT_NACOS_PORT', '18848')}"
    data = urllib.parse.urlencode({
        'username': os.environ['SMARTLECT_NACOS_USERNAME'],
        'password': os.environ['SMARTLECT_NACOS_PASSWORD'],
    }).encode()
    resp = urllib.request.urlopen(urllib.request.Request(
        f'{base}/nacos/v1/auth/login', data=data), timeout=5)
    return json.load(resp)['accessToken'], base


def push_config(token, base, data_id, content):
    import urllib.request
    import urllib.parse
    import os
    data = urllib.parse.urlencode({
        'accessToken': token,
        'dataId': data_id,
        'group': GROUP,
        'content': content,
        'type': 'yaml',
    }).encode()
    resp = urllib.request.urlopen(urllib.request.Request(
        f'{base}/nacos/v1/cs/configs', data=data), timeout=5)
    body = resp.read().decode()
    return body == 'true'


def strip_self_import(content):
    """剥离服务 yml 里的 `- nacos:...` 导入行，其余原样保留。

    这份内容会被应用从配置中心拉回来；若仍声明"从 Nacos 导入"，就会顺着
    spring.config.import 递归拉取自身。本地 classpath 兜底那行予以保留。
    找不到可剥离的行时返回 None——宁可跳过推送，也不把自引用写进配置中心。
    """
    kept = [line for line in content.splitlines(keepends=True)
            if not re.match(r'\s*- (optional:)?nacos:', line)]
    if len(kept) == len(content.splitlines()):
        return None
    return ''.join(kept)


def main():
    load_env()
    token, base = nacos_login()
    print(f'Nacos 登录成功 → {base}')

    # 公共配置
    common = COMMON_YML.read_text()
    if push_config(token, base, 'smartlect-common.yml', common):
        print(f'OK smartlect-common.yml ({len(common)} chars)')

    # 服务配置
    targets = sys.argv[1:] if len(sys.argv) > 1 else SERVICES
    for svc in targets:
        app_yml = ROOT / f'backend/{svc}/app/src/main/resources/application.yml'
        if svc in ('smartlect-gateway', 'smartlect-admin'):
            app_yml = ROOT / f'backend/{svc}/src/main/resources/application.yml'
        if not app_yml.exists():
            print(f'!! {svc}: application.yml 不存在')
            continue
        content = strip_self_import(app_yml.read_text())
        if content is None:
            print(f'!! {svc}: 未找到 Nacos 导入行，拒绝推送（否则配置中心会自引用拉取自身）')
            continue
        if push_config(token, base, f'{svc}.yml', content):
            print(f'OK {svc}.yml ({len(content)} chars)')


if __name__ == '__main__':
    main()
