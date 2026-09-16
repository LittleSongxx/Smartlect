package com.smartlect.redis;

import org.junit.jupiter.api.Test;
import org.redisson.config.Config;
import org.redisson.config.SentinelServersConfig;
import org.redisson.config.SingleServerConfig;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class RedissionConfigTest {

    @Test
    void appliesAclDatabaseAndTlsSettings() {
        RedissionConfig configuration = new RedissionConfig(
                "redis.internal",
                6380,
                "smartlect",
                "p@ss:/?#[]",
                3,
                true);

        Config config = configuration.buildConfig();
        SingleServerConfig server = config.useSingleServer();

        assertEquals("rediss://redis.internal:6380", server.getAddress());
        assertEquals("smartlect", config.getUsername());
        assertEquals("p@ss:/?#[]", config.getPassword());
        assertEquals(3, server.getDatabase());
    }

    @Test
    void leavesOptionalCredentialsUnsetForLegacyLocalRedis() {
        RedissionConfig configuration = new RedissionConfig(
                "127.0.0.1",
                6380,
                "",
                "",
                0,
                false);

        Config config = configuration.buildConfig();
        SingleServerConfig server = config.useSingleServer();

        assertEquals("redis://127.0.0.1:6380", server.getAddress());
        assertNull(config.getUsername());
        assertNull(config.getPassword());
        assertEquals(0, server.getDatabase());
    }

    @Test
    void followsTheSentinelMasterWhenSentinelNodesAreConfigured() {
        // 集群形态：Redis 由 sentinel 选主，Redisson 必须跟随，否则会被钉在副本上
        // （写命令 READONLY，每次重试数秒；线上表现为商品详情卡 5 秒）。
        RedissionConfig configuration = new RedissionConfig(
                "127.0.0.1", 16379, "", "secret", 0, false, "mymaster",
                "172.21.131.151:26379, 172.19.34.202:26379");

        Config config = configuration.buildConfig();
        SentinelServersConfig sentinel = config.useSentinelServers();

        assertEquals("mymaster", sentinel.getMasterName());
        assertEquals(0, sentinel.getDatabase());
        assertEquals(2, sentinel.getSentinelAddresses().size());
        assertEquals("redis://172.21.131.151:26379", sentinel.getSentinelAddresses().get(0));
        assertEquals("redis://172.19.34.202:26379", sentinel.getSentinelAddresses().get(1));
        assertEquals("secret", config.getPassword());
    }

    @Test
    void staysOnSingleServerWithoutSentinelConfiguration() {
        RedissionConfig configuration = new RedissionConfig(
                "127.0.0.1", 16379, "", "", 0, false, "", "");
        assertEquals("redis://127.0.0.1:16379", configuration.buildConfig().useSingleServer().getAddress());
    }
}
