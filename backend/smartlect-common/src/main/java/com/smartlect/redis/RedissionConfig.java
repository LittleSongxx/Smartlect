package com.smartlect.redis;

import lombok.extern.slf4j.Slf4j;
import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.client.RedisConnectionException;
import org.redisson.config.Config;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;

@Configuration
@Slf4j
public class RedissionConfig {

    private final String redisHost;
    private final int redisPort;
    private final String redisUsername;
    private final String redisPassword;
    private final int redisDatabase;
    private final boolean redisSslEnabled;
    private final String sentinelMaster;
    private final String sentinelNodes;

    public RedissionConfig(
            @Value("${spring.data.redis.host:127.0.0.1}") String redisHost,
            @Value("${spring.data.redis.port:16379}") int redisPort,
            @Value("${spring.data.redis.username:}") String redisUsername,
            @Value("${spring.data.redis.password:}") String redisPassword,
            @Value("${spring.data.redis.database:0}") int redisDatabase,
            @Value("${spring.data.redis.ssl.enabled:false}") boolean redisSslEnabled,
            @Value("${spring.data.redis.sentinel.master:}") String sentinelMaster,
            @Value("${spring.data.redis.sentinel.nodes:}") String sentinelNodes) {
        this.redisHost = redisHost;
        this.redisPort = redisPort;
        this.redisUsername = redisUsername;
        this.redisPassword = redisPassword;
        this.redisDatabase = redisDatabase;
        this.redisSslEnabled = redisSslEnabled;
        this.sentinelMaster = sentinelMaster;
        this.sentinelNodes = sentinelNodes;
    }

    /** 单机形态（本地开发/单机部署）的便捷构造：不配 sentinel。 */
    public RedissionConfig(String redisHost, int redisPort, String redisUsername, String redisPassword,
                           int redisDatabase, boolean redisSslEnabled) {
        this(redisHost, redisPort, redisUsername, redisPassword, redisDatabase, redisSslEnabled, "", "");
    }

    @Bean(value = "redissonClient", destroyMethod = "shutdown")
    public RedissonClient redissonClient() {
        try {
            RedissonClient redissonClient = Redisson.create(buildConfig());
            log.info("RedissonClient 创建成功：sentinel 主={} 节点={}（空则单机 {}:{}）",
                    sentinelMaster, sentinelNodes, redisHost, redisPort);
            return redissonClient;
        } catch (RedisConnectionException e) {
            log.error("RedissonClient 创建失败，Redis 连接异常: {}://{}:{}",
                    redisSslEnabled ? "rediss" : "redis", redisHost, redisPort, e);
            throw new RuntimeException("Redis 连接失败，请检查 Redis 服务是否启动", e);
        }
    }

    Config buildConfig() {
        Config config = new Config();
        String scheme = redisSslEnabled ? "rediss://" : "redis://";
        if (StringUtils.hasText(sentinelMaster) && StringUtils.hasText(sentinelNodes)) {
            // 集群形态下 Redis 由 sentinel 选主（Spring 自身的客户端就是这样配的）。只读
            // host/port 会把 Redisson 钉死在某个副本上：写命令返回 READONLY、重试数秒才失败，
            // 表现就是"每看一次商品详情卡约 5 秒"（布隆过滤器预热写）。这里与 Spring 客户端同源。
            var sentinel = config.useSentinelServers()
                    .setMasterName(sentinelMaster.trim())
                    .setDatabase(redisDatabase)
                    .setScanInterval(2000)
                    // sentinel 上报的地址在容器/内网映射下可能与真实地址不同，跳过列表校验
                    .setCheckSentinelsList(false);
            for (String node : sentinelNodes.split(",")) {
                if (StringUtils.hasText(node)) {
                    sentinel.addSentinelAddress(scheme + node.trim());
                }
            }
        } else {
            config.useSingleServer().setAddress(scheme + redisHost + ":" + redisPort).setDatabase(redisDatabase);
        }
        if (StringUtils.hasText(redisUsername)) {
            config.setUsername(redisUsername);
        }
        if (StringUtils.hasText(redisPassword)) {
            config.setPassword(redisPassword);
        }
        return config;
    }
}
