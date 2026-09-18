"""Read only the reviewed, packaged business skills. Documents cannot install code."""
import json
from importlib.resources import files

USER_SKILLS = ("shopping_advice", "support_policy", "order_service")


def load_skill(skill_id, *, domain="shopping"):
    allowed = USER_SKILLS if domain == "shopping" else ()
    if skill_id not in allowed:
        raise ValueError("skill_not_allowed")
    return json.loads(files("smartlect").joinpath("skills", skill_id + ".json").read_text())


def catalog(*, domain="shopping"):
    allowed = USER_SKILLS if domain == "shopping" else ()
    return [{key: value for key, value in load_skill(name, domain=domain).items() if key in {"skill_id", "version", "intents"}}
            for name in allowed]
