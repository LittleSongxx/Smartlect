"""Two live category systems stay separate; this table only records the correspondence.

Shopping/catalog slugs (`desk`/`audio`/`acc`/`furn`) are the storefront merchandising
tree. Ads inference still uses the historical `200xx` identifiers from browse/order
snapshots. Do not migrate live catalog rows onto the other system.
"""

STORE_CATEGORIES = frozenset({'desk', 'audio', 'acc', 'furn'})

ADS_INFERENCE_CATEGORIES = frozenset({
    '20021', '20022', '20023', '20033', '20019', '20011', '20012', '20016',
    '20003', '20007', '20028', '20015', '88409', '20001', '20002',
})

# Explicit merchandising correspondence only. Empty means no shared intent.
STORE_TO_ADS = {
    'desk': (),
    'audio': ('20003',),
    'acc': ('20033', '20001', '20002'),
    'furn': ('20016', '20019'),
}

ADS_TO_STORE = {
    ads_id: store
    for store, ads_ids in STORE_TO_ADS.items()
    for ads_id in ads_ids
}


def store_category_for_ads_id(category_id):
    if category_id is None:
        return None
    return ADS_TO_STORE.get(str(category_id))


def ads_ids_for_store_category(store_slug):
    if store_slug is None:
        return ()
    return STORE_TO_ADS.get(str(store_slug), ())


def compatible_category(store_slug, ads_id):
    mapped = store_category_for_ads_id(ads_id)
    return mapped is not None and mapped == store_slug
