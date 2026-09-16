"""Admin-only ops surface for AI assets.

New admin-api endpoints live in this package as APIRouter modules instead of growing
app.py; create_app stays the single composition root. Everything here requires a
merchant actor with admin:legacy and (for writes) the shared CSRF check, exactly like
the existing admin endpoints in app.py.
"""
from . import knowledge_ops, models, runs, tools


def register(app, *, actor_for, store, commerce, knowledge, attribution, provider, config, settings, shopping_retrieve, indexing):
    app.include_router(runs.build_router(actor_for=actor_for, connect=store.connect))
    app.include_router(tools.build_router(
        actor_for=actor_for, store=store, commerce=commerce, knowledge=knowledge,
        attribution=attribution, provider=provider, config=config, settings=settings,
        shopping_retrieve=shopping_retrieve))
    app.include_router(knowledge_ops.build_router(
        actor_for=actor_for, indexing=indexing, knowledge=knowledge,
        provider=provider, config=config, settings=settings, commerce=commerce))
    app.include_router(models.build_router(actor_for=actor_for, connect=store.connect,
                                           provider=provider, config=config))
