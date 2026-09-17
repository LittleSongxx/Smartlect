package com.smartlect.cloud.gateway.support;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpCookie;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class GatewayTokenResolverTest {

    @Test
    void queryStringTokenIsNeverAccepted() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/orders?token=leaked-token").build());

        assertNull(GatewayTokenResolver.resolveWebToken(exchange));
    }

    @Test
    void cookieTakesPrecedenceOverCustomHeaderAndBearerIsFallback() {
        MockServerWebExchange cookieWins = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/orders")
                        .header("token", " header-token ")
                        .header("Authorization", "Bearer bearer-token")
                        .cookie(new HttpCookie("token", "cookie-token"))
                        .build());
        assertEquals("cookie-token", GatewayTokenResolver.resolveWebToken(cookieWins));

        MockServerWebExchange headerOnly = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/orders")
                        .header("token", " header-token ")
                        .header("Authorization", "Bearer bearer-token")
                        .build());
        assertEquals("header-token", GatewayTokenResolver.resolveWebToken(headerOnly));

        MockServerWebExchange bearerOnly = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/orders")
                        .header("Authorization", "Bearer bearer-token")
                        .build());
        assertEquals("bearer-token", GatewayTokenResolver.resolveWebToken(bearerOnly));
    }
}
