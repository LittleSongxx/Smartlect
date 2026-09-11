package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RBloomFilter;
import org.redisson.api.RedissonClient;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
@Slf4j
public class ProductBloomFilterComponent {

    @Resource
    private RedissonClient redissonClient;
    @Resource
    private ProductInfoMapper<?, ?> productInfoMapper;

    private volatile boolean ready;

    public void add(String productId) {
        if (StringTools.isEmpty(productId)) {
            return;
        }
        try {
            ensureInitialized();
            getBloomFilter().add(productId);
        } catch (Exception e) {
            log.warn("商品布隆过滤器写入失败 productId={}", productId, e);
        }
    }

    public boolean mightExist(String productId) {
        if (StringTools.isEmpty(productId)) {
            return false;
        }
        if (!ready) {
            return true;
        }
        try {
            if (getBloomFilter().contains(productId)) {
                return true;
            }
            // ponytail: a negative now costs one DB read; optimize miss floods only if measured.
            // Java demo imports and a failed cache write can leave an existing
            // database product absent from this advisory filter.
            if (productInfoMapper.selectByProductId(productId) == null) {
                return false;
            }
            add(productId);
            return true;
        } catch (Exception e) {
            log.warn("商品布隆过滤器查询失败 productId={}", productId, e);
            return true;
        }
    }

    @EventListener(ApplicationReadyEvent.class)
    public void warmUpAllProductsOnStartup() {
        synchronized (this) {
            if (ready) {
                return;
            }
            try {
                RBloomFilter<String> filter = getBloomFilter();
                filter.tryInit(Constants.PRODUCT_BLOOM_EXPECTED_INSERTIONS, Constants.PRODUCT_BLOOM_FALSE_PROBABILITY);
                List<String> productIds = productInfoMapper.selectAllProductIds();
                for (String productId : productIds) {
                    if (!StringTools.isEmpty(productId)) {
                        filter.add(productId);
                    }
                }
                ready = true;
                log.info("商品布隆过滤器已预热全量商品 {} 个", productIds.size());
            } catch (Exception e) {
                log.error("商品布隆过滤器预热失败，查商品时将降级为直接查库", e);
            }
        }
    }

    private void ensureInitialized() {
        RBloomFilter<String> filter = getBloomFilter();
        filter.tryInit(Constants.PRODUCT_BLOOM_EXPECTED_INSERTIONS, Constants.PRODUCT_BLOOM_FALSE_PROBABILITY);
    }

    private RBloomFilter<String> getBloomFilter() {
        return redissonClient.getBloomFilter(Constants.REDIS_KEY_PRODUCT_BLOOM);
    }
}
