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
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            assertEquals("internal-test", exchange.getRequestHeaders().getFirst("X-Internal-Token"));
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            assertTrue(requestBody.contains("\"userId\":\"u1\""));
            assertTrue(requestBody.contains("\"requestId\":\"request-1\""));
            assertTrue(requestBody.contains("\"skuKey\":\"sku-1\""));
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
        server.createContext("/internal/attribution/validateBatch", exchange -> {
            String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            assertEquals(1, body.split("\\\"requestId\\\"", -1).length - 1);
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
        return new RecommendationAttributionClient(
                RestClient.builder(),
                "http://127.0.0.1:" + port,
                "internal-test",
                100,
                200);
    }

    private static void respond(HttpExchange exchange, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
