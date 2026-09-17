package com.smartlect.utils;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Fact-axis content. Specification axes stay on SKU property values;
 * these columns never participate in the SKU hash.
 */
public final class ProductContentJson {

    public static final String[] SECTION_KEYS = {
            "selling_points", "usage", "ingredients", "packaging",
            "contraindications", "after_sale_note"
    };

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private ProductContentJson() {
    }

    public static Map<String, Object> toContentMap(String contentJson, String productDesc) {
        Map<String, Object> raw = parse(contentJson);
        Map<String, Object> content = new LinkedHashMap<>();
        for (String key : SECTION_KEYS) {
            String value = ProductIndexTextSanitizer.sanitize(asText(raw.get(key)));
            if (!value.isEmpty()) {
                content.put(key, value);
            }
        }
        String extra = ProductIndexTextSanitizer.sanitize(asText(raw.get("extra_markdown")));
        if (extra.isEmpty()) {
            extra = ProductIndexTextSanitizer.sanitize(productDesc);
        }
        if (!extra.isEmpty()) {
            content.put("extra_markdown", extra);
        }
        return content;
    }

    public static String firstBrand(String columnBrand, String propertyBrand) {
        String fromColumn = ProductIndexTextSanitizer.sanitize(columnBrand);
        if (!fromColumn.isEmpty()) {
            return fromColumn.length() > 100 ? fromColumn.substring(0, 100) : fromColumn;
        }
        String fromProperty = ProductIndexTextSanitizer.sanitize(propertyBrand);
        return fromProperty.isEmpty() ? null : fromProperty;
    }

    static Map<String, Object> parse(String contentJson) {
        if (contentJson == null || contentJson.isBlank()) {
            return Map.of();
        }
        try {
            Map<String, Object> parsed = MAPPER.readValue(contentJson, MAP_TYPE);
            return parsed == null ? Map.of() : parsed;
        } catch (Exception ignored) {
            return Map.of();
        }
    }

    private static String asText(Object value) {
        return value == null ? "" : String.valueOf(value);
    }
}
