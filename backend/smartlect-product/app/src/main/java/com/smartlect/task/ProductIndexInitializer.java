package com.smartlect.task;

import com.smartlect.search.ProductIndexService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.task.AsyncTaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

/**
 * 商品索引全量初始化：索引不存在或为空时全量重建。
 *
 * <p>Canal 只管增量且位点从启动时刻开始订阅——全新部署的存量商品必须由本初始化器
 * 补进索引；非空索引不重刷（增量由消费者维持），避免每次重启全量抖动。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "smartlect.canal.index-enabled", havingValue = "true", matchIfMissing = true)
public class ProductIndexInitializer implements ApplicationRunner {

    private final ProductIndexService indexService;

    public ProductIndexInitializer(ProductIndexService indexService) {
        this.indexService = indexService;
    }

    @Override
    public void run(ApplicationArguments args) {
        // 异步执行：87k 商品全量重建需数分钟，阻塞主线程会拖死健康检查（曾导致启动超时被杀）。
        // 检索在索引就绪前自动回退 SQL LIKE，服务可用性不受重建进度影响。
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("product-index-init-");
        executor.setDaemon(true);
        executor.initialize();
        executor.execute(() -> {
            if (!indexService.ensureIndex()) {
                log.warn("ES 不可达，商品索引初始化跳过（查询将回退 SQL LIKE，待 ES 恢复后重启补全）");
                return;
            }
            indexService.rebuildAll(500);
        });
    }
}
