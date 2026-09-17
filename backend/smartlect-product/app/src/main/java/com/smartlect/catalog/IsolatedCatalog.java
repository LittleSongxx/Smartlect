package com.smartlect.catalog;

/**
 * Isolated / eval catalogue is an explicit catalog_scope, not a product_id prefix guess.
 * Java search and Growth eligibility both honor this column; 9100/9300 prefixes are only
 * a one-time SQL backfill heuristic when the column is missing.
 */
public final class IsolatedCatalog {

    public static final String SCOPE_STORE = "store";
    public static final String SCOPE_EVAL = "eval";

    private IsolatedCatalog() {
    }

    public static boolean isEvalScope(String catalogScope) {
        return SCOPE_EVAL.equalsIgnoreCase(catalogScope);
    }

    public static boolean looksLikeIsolatedSearch(String keyword) {
        if (keyword == null) {
            return false;
        }
        String trimmed = keyword.trim();
        return trimmed.startsWith("scope:eval") || trimmed.startsWith("catalog_scope=eval");
    }
}
