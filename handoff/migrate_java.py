"""One-time frozen-source import; never used by builds or application startup."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = root / 'handoff/extracted/commerce-java/AI_Shop-backend'
target = root / 'backend'
if target.exists():
    raise SystemExit('backend already exists; refusing to overwrite implementation')

def rename(value):
    for old, new in [('AI_Shop-', 'smartlect-'), ('AI_Shop', 'Smartlect'),
                     ('AISHOP', 'SMARTLECT'), ('aishop', 'smartlect'),
                     ('Smarlect', 'Smartlect'), ('Simlect', 'Smartlect'),
                     ('smarlect', 'smartlect'), ('simlect', 'smartlect'),
                     ('ECOM_', 'SMARTLECT_'), ('mall:', 'smartlect:')]:
        value = value.replace(old, new)
    for old, new in [('aiRequestId', 'recommendationRequestId'),
                     ('aiPosition', 'recommendationPosition'),
                     ('aiSource', 'recommendationSource'),
                     ('aiAttributedAt', 'recommendationAttributedAt'),
                     ('AiRequestId', 'RecommendationRequestId'),
                     ('AiPosition', 'RecommendationPosition'),
                     ('AiSource', 'RecommendationSource'),
                     ('AiAttributedAt', 'RecommendationAttributedAt'),
                     ('ai_request_id', 'recommendation_request_id'),
                     ('ai_position', 'recommendation_position'),
                     ('ai_source', 'recommendation_source'),
                     ('ai_attributed_at', 'recommendation_attributed_at')]:
        value = value.replace(old, new)
    for name in ('Admin', 'Gateway', 'User', 'Product', 'Stock', 'Cart', 'Order', 'Pay', 'Coupon'):
        value = re.sub(r'\b' + name + r'Application\b', 'Smartlect' + name + 'Application', value)
    return value

count = 0
for path in source.rglob('*'):
    if not path.is_file() or path.relative_to(source).parts[0] == 'AI_Shop-search':
        continue
    if path.name == 'pom.xml.txt':  # duplicate, unused source reference
        continue
    out = target / rename(path.relative_to(source).as_posix())
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        body = rename(path.read_text(encoding='utf-8-sig'))
    except UnicodeDecodeError:
        out.write_bytes(path.read_bytes())
        continue
    if path.name == 'pom.xml':
        body = body.replace('<version>1.0.0</version>', '<version>0.1.0-SNAPSHOT</version>')
        body = re.sub(r'\s*<module>smartlect-search</module>', '', body)
        body = re.sub(r'\s*<spring.ai.version>.*?</spring.ai.version>', '', body)
        body = re.sub(r'\s*<dependency>\s*<groupId>org.springframework.ai</groupId>.*?</dependency>', '', body, flags=re.S)
    out.write_text(body, encoding='utf-8')
    count += 1
(target / 'LICENSE.md').write_bytes((source.parent / 'LICENSE.md').read_bytes())
print(f'Imported {count} text files to backend; search and unused pom copies excluded')
