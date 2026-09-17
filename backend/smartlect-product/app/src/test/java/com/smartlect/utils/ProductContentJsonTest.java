package com.smartlect.utils;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class ProductContentJsonTest {

    @Test
    void oldMarkdownBecomesExtraWhenContentJsonMissing() {
        Map<String, Object> content = ProductContentJson.toContentMap(null, "整篇旧描述<script>");
        assertEquals("整篇旧描述", content.get("extra_markdown"));
        assertFalse(content.containsKey("ingredients"));
    }

    @Test
    void sectionsWinAndExtraFallsBackToProductDesc() {
        String json = "{\"ingredients\":\"水, 甘油\",\"selling_points\":\"<b>保湿</b>\"}";
        Map<String, Object> content = ProductContentJson.toContentMap(json, "旧 Markdown");
        assertEquals("水, 甘油", content.get("ingredients"));
        assertEquals("保湿", content.get("selling_points"));
        assertEquals("旧 Markdown", content.get("extra_markdown"));
    }

    @Test
    void extraMarkdownInJsonOverridesProductDesc() {
        String json = "{\"extra_markdown\":\"栏目描述\",\"usage\":\"每日两次\"}";
        Map<String, Object> content = ProductContentJson.toContentMap(json, "会被覆盖的旧文");
        assertEquals("栏目描述", content.get("extra_markdown"));
        assertEquals("每日两次", content.get("usage"));
    }

    @Test
    void invalidJsonDoesNotBreakSaveProjection() {
        Map<String, Object> content = ProductContentJson.toContentMap("{not-json", "还能用");
        assertEquals("还能用", content.get("extra_markdown"));
    }

    @Test
    void columnBrandBeatsPropertyBrand() {
        assertEquals("列上的品牌", ProductContentJson.firstBrand("列上的品牌", "属性品牌"));
        assertEquals("属性品牌", ProductContentJson.firstBrand("  ", "属性品牌"));
        assertNull(ProductContentJson.firstBrand(null, null));
    }
}
