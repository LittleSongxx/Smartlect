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
    // 这个写入是可选的加速项（布隆过滤器只用于提前挡掉不存在的商品 id）。Redis 只读或抖动时
    // 每次重试要数秒，会让商品详情这类热路径变慢，所以失败后进入冷却：冷却期内直接跳过写入，
    // 让它退化成"不加缓存"，而不是"每请求卡几秒"。
    private static final long WRITE_COOLDOWN_MILLIS = 60_000L;
    private volatile long writeCooldownUntil;

    public void add(String productId) {
        if (StringTools.isEmpty(productId)) {
            return;
        }
        if (System.currentTimeMillis() < writeCooldownUntil) {
            return;
        }
        try {
            ensureInitialized();
            getBloomFilter().add(productId);
        } catch (Exception e) {
            writeCooldownUntil = System.currentTimeMillis() + WRITE_COOLDOWN_MILLIS;
            log.warn("商品布隆过滤器写入失败，{} 秒内跳过该可选写入 productId={}",
                    WRITE_COOLDOWN_MILLIS / 1000, productId, e);
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
