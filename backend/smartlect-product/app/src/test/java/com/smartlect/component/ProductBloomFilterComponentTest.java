package com.smartlect.component;

import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.mappers.ProductInfoMapper;
import org.junit.jupiter.api.Test;
import org.redisson.api.RBloomFilter;
import org.redisson.api.RedissonClient;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ProductBloomFilterComponentTest {
    @Test
    @SuppressWarnings("unchecked")
    void negativeCacheCannotHideAnExistingJavaProduct() {
        RedissonClient redis = mock(RedissonClient.class);
        RBloomFilter<String> filter = mock(RBloomFilter.class);
        ProductInfoMapper<ProductInfo, ProductInfoQuery> mapper = mock(ProductInfoMapper.class);
        when(redis.<String>getBloomFilter(anyString())).thenReturn(filter);
        ProductBloomFilterComponent component = new ProductBloomFilterComponent();
        ReflectionTestUtils.setField(component, "redissonClient", redis);
        ReflectionTestUtils.setField(component, "productInfoMapper", mapper);
        ReflectionTestUtils.setField(component, "ready", true);
        when(mapper.selectByProductId("new-demo-product")).thenReturn(new ProductInfo());
        assertTrue(component.mightExist("new-demo-product"));
        verify(filter).add("new-demo-product");
        assertFalse(component.mightExist("nonexistent"));
        verify(filter, never()).add("nonexistent");
        when(filter.contains("already-indexed")).thenReturn(true);
        assertTrue(component.mightExist("already-indexed"));
        verify(mapper, never()).selectByProductId("already-indexed");
    }
}
