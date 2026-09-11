"""One-time namespace/config migration, not an application dependency."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'backend'
defaults = {
    'SMARTLECT_MYSQL_PORT':'13306', 'SMARTLECT_MYSQL_USER':'smartlect_app',
    'SMARTLECT_MYSQL_PASSWORD':'', 'SMARTLECT_REDIS_PORT':'16379',
    'SMARTLECT_RABBIT_PORT':'15672', 'SMARTLECT_RABBIT_USER':'smartlect',
    'SMARTLECT_RABBIT_PASSWORD':'', 'SMARTLECT_RABBIT_VHOST':'smartlect',
    'SMARTLECT_NACOS_ADDR':'127.0.0.1:18848', 'SMARTLECT_NACOS_PASSWORD':'',
    'SMARTLECT_NACOS_GROUP':'SMARTLECT_GROUP', 'SMARTLECT_NACOS_NAMESPACE':'',
    'SMARTLECT_INTERNAL_TOKEN':'', 'SMARTLECT_ADMIN_PASSWORD':'',
    'SMARTLECT_PROJECT_FOLDER':'./run/uploads/',
    'SMARTLECT_SENTINEL_DASHBOARD':'',
}
ports = {'gateway':18080,'admin':18081,'user':18082,'product':18083,'stock':18084,
         'cart':18085,'order':18086,'pay':18087,'coupon':18088}
for path in root.rglob('*'):
    if not path.is_file() or path.suffix not in ('.yml','.yaml'):
        continue
    s = path.read_text()
    s = s.replace('  agent:\n','  growth:\n').replace('AGENT_BASE_URL','SMARTLECT_GROWTH_BASE_URL').replace('AGENT_ATTRIBUTION_','SMARTLECT_GROWTH_ATTRIBUTION_')
    s = re.sub(r'\$\{([A-Z][A-Z0-9_]*)([:}])', lambda m: '${' + (m[1] if m[1].startswith('SMARTLECT_') else 'SMARTLECT_' + m[1]) + m[2], s)
    for key,value in defaults.items():
        s = re.sub(r'\$\{' + key + r':[^}]*}', '${' + key + ':' + value + '}', s)
    if path.name == 'application.yml':
        service = path.relative_to(root).parts[0].removeprefix('smartlect-')
        s = re.sub(r'\$\{SMARTLECT_SERVER_PORT:[0-9]+}', '${SMARTLECT_' + service.upper() + '_PORT:' + str(ports[service]) + '}', s)
    s = s.replace('group: SEATA_GROUP', 'group: SMARTLECT_SEATA_GROUP').replace('application: seata-server','application: smartlect-seata')
    s = s.replace('  ai-chat-limit: ${SMARTLECT_PROJECT_AI_CHAT_LIMIT:0}\n','')
    s = s.replace('http://127.0.0.1:7050','http://127.0.0.1:18000')
    path.write_text(s)

# No legacy default token, server URL or shared discovery is allowed in code either.
for module in ('smartlect-common','smartlect-gateway','smartlect-cart','smartlect-order','smartlect-pay','smartlect-stock','smartlect-coupon'):
    for path in (root/module).rglob('*.java'):
        s = path.read_text()
        s = s.replace('${smartlect.internal.token:your-token}', '${smartlect.internal.token:}')
        s = s.replace('"commerce.outcome.queue"','"smartlect.growth.commerce.queue"')
        s = s.replace('"smartlect.commerce.outcome.queue"','"smartlect.growth.commerce.queue"')
        path.write_text(s)
print('Isolated service ports, environment variables and resource namespaces')
