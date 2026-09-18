"""DB-backed prompt and skill templates with the packaged code as the frozen fallback.

Hot editing is scoped to text: the static system policy per agent and the instruction
payload of the six packaged skills. Structure stays code-owned — a skill edit must keep
the packaged JSON schema, no new skill ids, no new tools; the system prompt is one text
block. Every run records the resolved version label in its context, so traces stay
attributable to the exact text that produced them.

Seeding happens from the code constants at startup (not from SQL) so there is exactly one
source for the text and a fresh deployment starts with zero behaviour change. Row
versions start at the code version number (v24/v19) so trace labels stay continuous.
"""
import json
import re

from smartlect.business_skills import USER_SKILLS, load_skill
from smartlect.state import SessionStore, StateError, _actor, _integer, _public, _text

SYSTEM_LABEL_PREFIX = {"shopping": "shopping-react", "rerank": "homepage-semantic-rerank"}
SKILL_KEYS = ("skill_id", "version", "intents", "knowledge", "tools",
              "output_contract", "instructions", "stop_conditions")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
MAX_SYSTEM_CHARS = 16000

# (domain, kind, key) -> {"body": str, "version": int}; registered by app startup from the
# agent modules so this module never imports the agents (no import cycle).
CODE_DEFAULTS = {}


def register_default(domain, kind, key, body, *, version):
    if kind == "system_prompt":
        _text(body, "body", MAX_SYSTEM_CHARS)
    CODE_DEFAULTS[(domain, kind, key)] = {"body": body, "version": _integer(version, "version", 1, 10 ** 9)}


def _code_version(label):
    digits = re.findall(r"(\d+)$", label or "")
    return int(digits[-1]) if digits else 1


class PromptStore(SessionStore):
    def seed_defaults(self):
        """Insert code constants as active rows when absent; surface newer code text as a draft.

        A row that already exists is never overwritten — that is what makes the console the
        live source of truth. But code can move on too (a new SYSTEM_POLICY_BODY shipped with
        a raised version label), and silently ignoring that would let production run text that
        no longer exists in the repo. So a higher code version lands as a visible DRAFT for an
        operator to review and activate, never as an automatic switch.
        """
        with self._transaction() as cursor:
            for (domain, kind, key), default in CODE_DEFAULTS.items():
                cursor.execute("SELECT COALESCE(MAX(version),0) AS latest FROM prompt_template "
                               "WHERE domain=%s AND kind=%s AND `key`=%s", (domain, kind, key))
                latest = cursor.fetchone()["latest"]
                if latest == 0:
                    status, note = "active", None
                elif default["version"] > latest:
                    status = "draft"
                    note = f"代码已更新到 v{default['version']}，当前激活 v{latest}；核对后手动激活"
                else:
                    continue
                cursor.execute("""INSERT INTO prompt_template
                    (domain,kind,`key`,version,body,meta_json,status,updated_by,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'code-seed',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                    (domain, kind, key, default["version"], default["body"],
                     json.dumps({"source": "code-default", "note": note} if note else {"source": "code-default"},
                                ensure_ascii=False), status))

    def active(self, domain, kind, key):
        with self._transaction() as cursor:
            cursor.execute("""SELECT * FROM prompt_template WHERE domain=%s AND kind=%s AND `key`=%s
                AND status='active' ORDER BY version DESC LIMIT 1""",
                (_text(domain, "domain", 16), _text(kind, "kind", 16), _text(key, "key", 64)))
            row = cursor.fetchone()
            return _public(row) if row else None

    def keys(self, domain):
        with self._transaction() as cursor:
            cursor.execute("""SELECT `key`,kind,COUNT(*) AS versions,MAX(version) AS latest,
                SUM(status='active') AS active_count FROM prompt_template WHERE domain=%s
                GROUP BY kind,`key` ORDER BY kind,`key`""", (_text(domain, "domain", 16),))
            return [_public(row) for row in cursor.fetchall()]

    def versions(self, domain, kind, key):
        with self._transaction() as cursor:
            cursor.execute("""SELECT id,version,status,updated_by,updated_at,LENGTH(body) AS size
                FROM prompt_template WHERE domain=%s AND kind=%s AND `key`=%s
                ORDER BY version DESC LIMIT 100""",
                (_text(domain, "domain", 16), _text(kind, "kind", 16), _text(key, "key", 64)))
            return [_public(row) for row in cursor.fetchall()]

    def body_of(self, domain, kind, key, version):
        with self._transaction() as cursor:
            cursor.execute("SELECT body FROM prompt_template WHERE domain=%s AND kind=%s AND `key`=%s AND version=%s",
                (_text(domain, "domain", 16), _text(kind, "kind", 16), _text(key, "key", 64),
                 _integer(version, "version", 1, 10 ** 9)))
            row = cursor.fetchone()
            if not row:
                raise StateError("prompt_version_not_found", 404)
            return {"body": row["body"]}

    def create_version(self, actor, domain, kind, key, body, meta=None):
        _actor(actor)
        if domain not in SYSTEM_LABEL_PREFIX:
            raise StateError("invalid_prompt_domain", 422)
        if kind == "system_prompt":
            key = "system"
            _text(body, "body", MAX_SYSTEM_CHARS)
            if not isinstance(body, str) or not body.strip():
                raise StateError("invalid_prompt_body", 422)
        elif kind == "skill":
            body = _validate_skill_body(domain, key, body)
        else:
            raise StateError("invalid_prompt_kind", 422)
        with self._transaction() as cursor:
            # FOR UPDATE over the whole series makes the next version number atomic: a bare
            # MAX(version)+1 lets two concurrent drafts compute the same version and one of
            # them dies on the unique key. On an empty series this takes the gap lock the
            # unique index provides, which serialises the first inserts too.
            cursor.execute("""SELECT version FROM prompt_template
                WHERE domain=%s AND kind=%s AND `key`=%s FOR UPDATE""", (domain, kind, key))
            version = max((row["version"] for row in cursor.fetchall()), default=0) + 1
            cursor.execute("""INSERT INTO prompt_template
                (domain,kind,`key`,version,body,meta_json,status,updated_by,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'draft',%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))""",
                (domain, kind, key, version, body,
                 json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else None, actor.actor_id))
            return {"domain": domain, "kind": kind, "key": key, "version": version, "status": "draft"}

    def activate(self, actor, domain, kind, key, version):
        _actor(actor)
        with self._transaction() as cursor:
            # Lock the whole (domain, kind, key) series, not just the target row: two
            # concurrent activations of different versions would otherwise each retire the
            # rows they can see and both end up 'active', and active() would then pick one
            # by version silently.
            cursor.execute("""SELECT id,version,status FROM prompt_template WHERE domain=%s AND kind=%s AND `key`=%s
                ORDER BY version FOR UPDATE""",
                (_text(domain, "domain", 16), _text(kind, "kind", 16), _text(key, "key", 64)))
            rows = cursor.fetchall()
            row = next((item for item in rows if item["version"] == version), None) if rows else None
            if not row:
                raise StateError("prompt_version_not_found", 404)
            if row["status"] == "active":
                return {"domain": domain, "kind": kind, "key": key, "version": version, "status": "active"}
            cursor.execute("""UPDATE prompt_template SET status='retired',updated_at=UTC_TIMESTAMP(6)
                WHERE domain=%s AND kind=%s AND `key`=%s AND status='active'""", (domain, kind, key))
            cursor.execute("""UPDATE prompt_template SET status='active',updated_by=%s,updated_at=UTC_TIMESTAMP(6)
                WHERE id=%s""", (actor.actor_id, row["id"]))
            return {"domain": domain, "kind": kind, "key": key, "version": version, "status": "active"}


def _validate_skill_body(domain, key, body):
    allowed = set(USER_SKILLS) if domain == "shopping" else set()
    if key not in allowed:
        # Documents cannot install code: editing is limited to the packaged skill set.
        raise StateError("skill_not_editable", 422)
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except ValueError:
        raise StateError("invalid_skill_json", 422) from None
    if not isinstance(data, dict) or set(data) != set(SKILL_KEYS) or data.get("skill_id") != key:
        raise StateError("invalid_skill_structure", 422)
    if not isinstance(data.get("version"), str) or not SEMVER.fullmatch(data["version"]):
        raise StateError("invalid_skill_version", 422)
    if not isinstance(data.get("instructions"), str) or not data["instructions"].strip():
        raise StateError("invalid_skill_instructions", 422)
    # tools is the one capability-bearing field: the agent's callable set is built from
    # these names (agents/shopping.py allowed_tools), so a text edit may narrow the
    # packaged list but never widen it, or the page would silently grant new tools.
    tools = data.get("tools")
    packaged = set(load_skill(key, domain=domain)["tools"])
    if (not isinstance(tools, list) or any(not isinstance(item, str) for item in tools)
            or not set(tools) <= packaged):
        raise StateError("skill_tools_not_authorized", 422)
    return json.dumps(data, ensure_ascii=False)


def resolve_system(connect, domain, default_body, fallback_label):
    """One SELECT per run; any failure falls back to the frozen code text."""
    row = None
    try:
        if connect is not None:
            row = PromptStore(connect).active(domain, "system_prompt", "system")
    except Exception:
        row = None
    if row and isinstance(row.get("body"), str) and row["body"].strip():
        prefix = SYSTEM_LABEL_PREFIX.get(domain, domain)
        return row["body"], f"{prefix}-v{row['version']}"
    return default_body, fallback_label


def resolve_skill(connect, domain, skill_id):
    try:
        if connect is not None:
            row = PromptStore(connect).active(domain, "skill", skill_id)
            if row and isinstance(row.get("body"), str):
                data = json.loads(row["body"])
                if data.get("skill_id") == skill_id:
                    return data
    except Exception:
        pass
    return load_skill(skill_id, domain=domain)


def seed(connect):
    if connect is None:
        return
    try:
        PromptStore(connect).seed_defaults()
    except Exception:
        pass  # seeding retries on next startup; agents fall back to code defaults meanwhile
