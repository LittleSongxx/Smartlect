"""Resolve execution_scope_id from the request or product ownership, never a mid-pipeline literal."""


def resolve_execution_scope(actor, *, request_scope=None, product_scope=None):
    if request_scope:
        return str(request_scope)
    if product_scope:
        return str(product_scope)
    return actor.execution_scope_id
