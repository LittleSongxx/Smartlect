package com.smartlect.controller.internal;

import com.smartlect.api.support.StockFeignSupport;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.*;

class ProductCommerceBatchDetailTest {
    private final ProductCommerceInternalController controller = new ProductCommerceInternalController();
    @SuppressWarnings("unchecked")
    private final ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper = mock(ProductInfoMapper.class);
    @SuppressWarnings("unchecked")
    private final ProductSkuMapper<ProductSku, ProductSkuQuery> productSkuMapper = mock(ProductSkuMapper.class);
    @SuppressWarnings("unchecked")
    private final ProductPropertyValueMapper<ProductPropertyValue, ProductPropertyValueQuery> propertyValueMapper =
            mock(ProductPropertyValueMapper.class);
    private final StockFeignSupport stockFeignSupport = mock(StockFeignSupport.class);

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(controller, "productInfoMapper", productInfoMapper);
        ReflectionTestUtils.setField(controller, "productSkuMapper", productSkuMapper);
        ReflectionTestUtils.setField(controller, "productPropertyValueMapper", propertyValueMapper);
        ReflectionTestUtils.setField(controller, "stockFeignSupport", stockFeignSupport);
        when(productSkuMapper.selectList(any())).thenReturn(List.of());
        when(propertyValueMapper.selectList(any())).thenReturn(List.of(
                property("品牌", "Smartlect")));
        when(stockFeignSupport.totalByProducts(anyList())).thenReturn(Map.of());
    }

    private ProductPropertyValue property(String name, String value) {
        ProductPropertyValue pv = new ProductPropertyValue();
        pv.setPropertyName(name);
        pv.setPropertyValue(value);
        return pv;
    }

    private ProductInfo product(String id, String description) {
        ProductInfo p = new ProductInfo();
        p.setProductId(id);
        p.setProductName("商品 " + id);
        p.setProductDesc(description);
        return p;
    }

    @Test
    void batchDetailReturnsSanitizedDetailsForEachExistingProduct() {
        when(productInfoMapper.selectList(any())).thenReturn(List.of(
                product("p1", "官方描述<script>alert(1)</script>"),
                product("p2", "第二个商品")));

        ResponseVO<List<Map<String, Object>>> response =
                controller.batchDetail(Map.of("productIds", List.of("p1", "p2", "missing")));

        assertNotNull(response.getData());
        assertEquals(2, response.getData().size());
        Map<String, Object> first = response.getData().get(0);
        assertEquals("p1", first.get("productId"));
        assertFalse(String.valueOf(first.get("description")).contains("<script>"));
        assertEquals("Smartlect", first.get("brand"));

        ArgumentCaptor<ProductInfoQuery> captor = ArgumentCaptor.forClass(ProductInfoQuery.class);
        verify(productInfoMapper).selectList(captor.capture());
        assertEquals(List.of("p1", "p2", "missing"), captor.getValue().getProductIdList());
    }

    @Test
    void batchDetailRejectsOversizedBatchesAndEmptyLists() {
        assertThrows(BusinessException.class, () -> controller.batchDetail(
                Map.of("productIds", java.util.stream.IntStream.rangeClosed(1, 51)
                        .mapToObj(i -> "p" + i).toList())));

        ResponseVO<List<Map<String, Object>>> empty = controller.batchDetail(Map.of());
        assertTrue(empty.getData().isEmpty());
    }
}
