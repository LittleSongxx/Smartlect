package com.smartlect.config;

import com.smartlect.component.ProductCacheService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.data.redis.listener.ChannelTopic;

/**
 * 商品缓存失效广播订阅：所有实例监听同一频道，
 * 收到失效事件后清本进程 L1（Caffeine），保证多实例一致性。
 */
@Configuration
public class ProductCacheListenerConfig {

    @Bean
    public RedisMessageListenerContainer productCacheListenerContainer(
            RedisConnectionFactory connectionFactory,
            ProductCacheService productCacheService) {
        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        container.addMessageListener((message, pattern) -> {
            String productId = new String(message.getBody());
            productCacheService.onInvalidationMessage(productId);
        }, new ChannelTopic(ProductCacheService.INVALIDATION_CHANNEL));
        return container;
    }
}
