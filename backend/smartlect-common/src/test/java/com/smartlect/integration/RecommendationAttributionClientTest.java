package com.smartlect.integration;

import com.smartlect.entity.po.ProductItem;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RecommendationAttributionClientTest {

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void appliesOnlyCanonicalServerFields() throws Exception {
        var receivedToken = new java.util.concurrent.atomic.AtomicReference<String>();
        var receivedBody = new java.util.concurrent.atomic.AtomicReference<String>();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        // 断言放在 handler 外：handler 线程里抛出的断言会被 HttpServer 吞掉，
        // 客户端只看到失败响应，真正的原因（请求没到 / 头不对）就丢了
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            receivedToken.set(exchange.getRequestHeaders().getFirst("X-Internal-Token"));
            receivedBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            respond(exchange, """
                    {"status":"success","code":200,"data":[{
                      "requestId":"request-1","productId":"p1","skuKey":"sku-1","position":2,
                      "source":"hybrid","occurredAt":"2026-08-06T09:00:00.123"
                    }]}
                    """);
        });
        server.start();

        ProductItem item = candidate();
        item.setRecommendationSource("forged-source");
        item.setRecommendationAttributedAt(new Date(1));
        client(server.getAddress().getPort()).validateAndApply("u1", List.of(item));

        assertEquals("internal-test", receivedToken.get(), "内部令牌没送到");
        assertNotNull(receivedBody.get(), "请求没到达：客户端把这次调用当成 assistant 不可用处理了");
        assertTrue(receivedBody.get().contains("\"userId\":\"u1\""), receivedBody.get());
        assertTrue(receivedBody.get().contains("\"requestId\":\"request-1\""), receivedBody.get());
        assertTrue(receivedBody.get().contains("\"skuKey\":\"sku-1\""), receivedBody.get());
        assertEquals("request-1", item.getRecommendationRequestId());
        assertEquals(2, item.getRecommendationPosition());
        assertEquals("hybrid", item.getRecommendationSource());
        assertNotNull(item.getRecommendationAttributedAt());
    }

    @Test
    void unavailableGrowthClearsOptionalAttributionWithoutThrowing() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        int unusedPort = server.getAddress().getPort();
        server.stop(0);
        server = null;

        ProductItem item = candidate();
        item.setRecommendationSource("forged-source");
        item.setRecommendationAttributedAt(new Date());

        client(unusedPort).validateAndApply("u1", List.of(item));

        assertNull(item.getRecommendationRequestId());
        assertNull(item.getRecommendationPosition());
        assertNull(item.getRecommendationSource());
        assertNull(item.getRecommendationAttributedAt());
    }

    @Test
    void oneValidatedSkuAppliesToEveryMatchingCarrierWithoutDuplicateRequests() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var receivedBody = new java.util.concurrent.atomic.AtomicReference<String>();
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            receivedBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            respond(exchange, """
                    {"status":"success","code":200,"data":[{
                      "requestId":"request-1","productId":"p1","skuKey":"sku-1","position":2,
                      "source":"hybrid","occurredAt":"2026-09-09T01:00:00Z"
                    }]}
                    """);
        });
        server.start();
        ProductItem first = candidate(), second = candidate();
        client(server.getAddress().getPort()).validateAndApply("u1", List.of(first, second));
        assertNotNull(receivedBody.get(), "请求没到达");
        assertEquals(1, receivedBody.get().split("\"requestId\"", -1).length - 1, "同一 SKU 不应重复请求");
        for (ProductItem item : List.of(first, second)) {
            assertEquals("request-1", item.getRecommendationRequestId());
            assertEquals("hybrid", item.getRecommendationSource());
            assertNotNull(item.getRecommendationAttributedAt());
        }
    }

    @Test
    void differentSkuOrLegacyResponseWithoutSkuCannotAttributeTheRequestedLine() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            exchange.getRequestBody().readAllBytes();
            respond(exchange, """
                    {"status":"success","code":200,"data":[null,{
                      "requestId":"request-1","productId":"p1","skuKey":"other-sku","position":2,
                      "source":"hybrid","occurredAt":"2026-09-09T01:00:00Z"
                    },{
                      "requestId":"request-1","productId":"p1","position":2,
                      "source":"legacy","occurredAt":"2026-09-09T01:00:00Z"
                    }]}
                    """);
        });
        server.start();
        ProductItem changed = candidate();
        changed.setRecommendationSource("forged-source");
        changed.setRecommendationAttributedAt(new Date());
        client(server.getAddress().getPort()).validateAndApply("u1", List.of(changed));
        assertNull(changed.getRecommendationRequestId());
        assertNull(changed.getRecommendationPosition());
        assertNull(changed.getRecommendationSource());
        assertNull(changed.getRecommendationAttributedAt());
    }

    @Test
    void missingSkuClearsLegacyAttributionBeforeAnyNetworkCall() throws Exception {
        var requests = new java.util.concurrent.atomic.AtomicInteger();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            requests.incrementAndGet();
            exchange.getRequestBody().readAllBytes();
            respond(exchange, "{\"status\":\"success\",\"code\":200,\"data\":[]}");
        });
        server.start();
        ProductItem item = candidate();
        item.setPropertyValueIdHash(null);
        item.setRecommendationSource("forged-source");
        item.setRecommendationAttributedAt(new Date());
        client(server.getAddress().getPort()).validateAndApply("u1", List.of(item));
        assertEquals(0, requests.get());
        assertNull(item.getRecommendationRequestId());
        assertNull(item.getRecommendationPosition());
        assertNull(item.getRecommendationSource());
        assertNull(item.getRecommendationAttributedAt());
    }

    private static ProductItem candidate() {
        ProductItem item = new ProductItem();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku-1");
        item.setRecommendationRequestId("request-1");
        item.setRecommendationPosition(2);
        return item;
    }

    private static RecommendationAttributionClient client(int port) {
        // 超时给宽裕值：这几条用例查的是字段归一化，不是超时行为。原来的 100/200ms 在负载较高的
        // CI 上会真的读超时，客户端按"assistant 不可用"降级清空字段，最终只表现为 requestId 为 null，
        // 排查时完全看不出是超时（2026-09-17 遇到过一次）。
        return new RecommendationAttributionClient(
                RestClient.builder(),
                "http://127.0.0.1:" + port,
                "internal-test",
                2000,
                3000);
    }

    private static void respond(HttpExchange exchange, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
