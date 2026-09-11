package com.smartlect.controller.internal;

import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductInfoMapper;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ProductCommerceSearchScopeTest {
    private final ProductCommerceInternalController controller = new ProductCommerceInternalController();
    @SuppressWarnings("unchecked")
    private final ProductInfoMapper<ProductInfo, ProductInfoQuery> mapper = mock(ProductInfoMapper.class);

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(controller, "productInfoMapper", mapper);
        when(mapper.selectList(any())).thenReturn(List.of());
    }

    @Test
    void scopesAreBoundInWhereBeforeExistingSortAndLimit() {
        controller.searchOnSale(Map.of("productIds", List.of("p1", "p2"),
                "excludeProductIds", List.of("p3' OR 1=1 --"),
                "keyword", "phone", "categoryId", "phones", "hotSale", true, "limit", 3));
        ProductInfoQuery query = capturedQuery();
        assertEquals(List.of("p1", "p2"), query.getProductIdList());
        assertEquals(List.of("p3' OR 1=1 --"), query.getExcludeProductIdList());
        assertEquals(ProductStatusEnum.ON_SALE.getStatus(), query.getStatus());
        assertEquals("phone", query.getProductNameFuzzy());
        assertEquals("phones", query.getCategoryId());
        assertEquals(3, query.getSimplePage().getEnd());

        BoundSql bound = boundSql(query);
        String sql = bound.getSql().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
        int where = sql.indexOf(" where ");
        int include = sql.indexOf("p.product_id in (");
        int exclude = sql.indexOf("p.product_id not in (");
        int sort = sql.indexOf(" order by p.total_sale desc");
        assertTrue(where >= 0 && include > where && exclude > include && sort > exclude);
        assertTrue(sql.indexOf(" limit ") > sort);
        assertFalse(sql.contains("p3'"));
        assertEquals(List.of("p1", "p2", "p3' OR 1=1 --"), bound.getParameterMappings().stream()
                .filter(parameter -> bound.hasAdditionalParameter(parameter.getProperty()))
                .map(parameter -> bound.getAdditionalParameter(parameter.getProperty())).toList());
    }

    @Test
    void omittedIncludeAndEmptyExcludeLeaveTheSearchUnrestricted() {
        controller.searchOnSale(Map.of("excludeProductIds", List.of(), "keyword", "category:phones"));
        ProductInfoQuery query = capturedQuery();
        assertNull(query.getProductIdList());
        assertEquals(List.of(), query.getExcludeProductIdList());
        assertEquals("phones", query.getCategoryId());
        assertNull(query.getProductNameFuzzy());
        assertEquals(20, query.getSimplePage().getEnd());
        String sql = boundSql(query).getSql().replaceAll("\\s+", " ");
        assertFalse(sql.contains("p.product_id in"));
        assertFalse(sql.contains("p.product_id not in"));
        assertTrue(sql.contains("order by p.create_time desc"));
    }

    @Test
    void emptyIncludeReturnsNoProductsWithoutQuerying() {
        assertEquals(List.of(), controller.searchOnSale(Map.of("productIds", List.of())).getData());
        verifyNoInteractions(mapper);
    }

    @Test
    void bothListsRejectMalformedValuesAndEnforceTheSameSizeBoundary() {
        for (String key : List.of("productIds", "excludeProductIds")) {
            for (Object invalid : Arrays.asList(null, "p1", Map.of("id", "p1"), List.of(1),
                    List.of(""), List.of(" \t"), List.of("p".repeat(65)), List.of("p\0x"),
                    Arrays.asList("p1", null),
                    Collections.nCopies(5001, "p1"))) {
                Map<String, Object> body = new HashMap<>();
                body.put("productIds", List.of());
                body.put(key, invalid);
                BusinessException failure = assertThrows(BusinessException.class,
                        () -> controller.searchOnSale(body), key);
                assertEquals(400, failure.getCode());
                assertEquals("invalid_" + key, failure.getMessage());
            }
        }
        verifyNoInteractions(mapper);
        List<String> boundary = Collections.nCopies(5000, "p".repeat(64));
        controller.searchOnSale(Map.of("productIds", boundary, "excludeProductIds", boundary));
        ProductInfoQuery query = capturedQuery();
        assertEquals(boundary, query.getProductIdList());
        assertEquals(boundary, query.getExcludeProductIdList());
    }

    private ProductInfoQuery capturedQuery() {
        ArgumentCaptor<ProductInfoQuery> capture = ArgumentCaptor.forClass(ProductInfoQuery.class);
        verify(mapper).selectList(capture.capture());
        return capture.getValue();
    }

    private static BoundSql boundSql(ProductInfoQuery query) {
        Configuration configuration = new Configuration();
        configuration.addMapper(ProductInfoMapper.class);
        return configuration.getMappedStatement(ProductInfoMapper.class.getName() + ".selectList")
                .getBoundSql(Map.of("query", query));
    }
}
