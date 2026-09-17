package com.smartlect.catalog;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class IsolatedCatalogTest {

    @Test
    void runtimeDoesNotGuessNumericPrefixes() {
        assertFalse(IsolatedCatalog.looksLikeIsolatedSearch("910000000000001"));
        assertFalse(IsolatedCatalog.looksLikeIsolatedSearch("Smartlect 演示"));
        assertTrue(IsolatedCatalog.looksLikeIsolatedSearch("scope:eval 演示"));
        assertTrue(IsolatedCatalog.isEvalScope("eval"));
        assertFalse(IsolatedCatalog.isEvalScope("store"));
    }
}
