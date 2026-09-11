-- Freeze the currently registered owner for legacy validated nonfinancial facts.
-- Reset preserves old resource mappings. A later registration/replay must not move
-- an already projected event, including one initially assigned to default store.
-- This migration changes no event bytes, fingerprint, money or financial attribution.
SELECT id FROM commerce_ledger_lock WHERE id=1 FOR UPDATE;
-- statement-break
INSERT INTO commerce_attribution_meta (event_id,execution_scope_id,metadata_json)
SELECT e.event_id,COALESCE(r.execution_scope_id,'store'),
       JSON_OBJECT('executionScopeId',COALESCE(r.execution_scope_id,'store'),
                   'scopeSource','registered_user_or_default_store',
                   'projectionVersion','nonfinancial-scope-v1',
                   'projectionSource','migration_0010',
                   'producerDeclaredScope',JSON_EXTRACT(e.raw_json,'$.payload.executionScopeId'))
FROM commerce_event e
LEFT JOIN execution_resource r ON r.resource_type='user' AND r.resource_id=e.user_id
LEFT JOIN commerce_attribution_meta existing ON existing.event_id=e.event_id
WHERE e.schema_version=1 AND e.status='APPLIED'
  AND e.event_type IN ('REPEAT_PURCHASE','ADD_TO_CART','REVIEW','CANCEL','VIEW')
  AND existing.event_id IS NULL
ON DUPLICATE KEY UPDATE event_id=commerce_attribution_meta.event_id;
