package com.smartlect.catalog;

/**
 * Eval / shelf-filler SKUs use 9100* and 9300* IDs. Real demo goods such as
 * 917186661226040 stay in the default store catalogue.
 */
public final class IsolatedCatalog {

    private IsolatedCatalog() {
    }

    public static boolean isIsolatedProductId(String productId) {
        if (productId == null || productId.length() < 4) {
            return false;
        }
        return productId.startsWith("9100") || productId.startsWith("9300");
    }

    public static boolean looksLikeIsolatedSearch(String keyword) {
        if (keyword == null) {
            return false;
        }
        String trimmed = keyword.trim();
        return trimmed.startsWith("9100") || trimmed.startsWith("9300")
                || trimmed.startsWith("Smartlect");
    }
}
