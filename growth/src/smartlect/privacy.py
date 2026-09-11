"""Credential redaction shared by durable text and model context boundaries."""
import os
import re

SECRET_FIELDS = ('SMARTLECT_MODEL_API_KEY', 'SMARTLECT_EMBEDDING_API_KEY', 'SMARTLECT_RERANK_API_KEY',
                 'SMARTLECT_INTERNAL_TOKEN', 'SMARTLECT_INTERNAL_OPS_TOKEN', 'SMARTLECT_VISITOR_SECRET',
                 'SMARTLECT_ATTRIBUTION_SECRET')


def redact_text(text, secrets=()):
    configured = set(SECRET_FIELDS) | {key for key in os.environ if key.startswith('SMARTLECT_')
                                     and key.endswith(('_PASSWORD', '_TOKEN', '_SECRET', '_API_KEY', '_IDENTITY'))}
    for secret in (*secrets, *(os.getenv(key, '') for key in configured)):
        if secret and len(secret) >= 8:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}\b', '[REDACTED]', text)
    text = re.sub(r'(?i)(?<![A-Za-z0-9_])([A-Za-z0-9_]*(?:api[_ -]?key|authorization|cookie|(?:admin)?token|password|passwd|secret))\s*[:=]\s*[^\s,;]+',
                  r'\1=[REDACTED]', text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(银行卡|信用卡|卡号)\s*[:：]?\s*[\d -]{13,25}', r'\1[REDACTED]', text)
    return text
