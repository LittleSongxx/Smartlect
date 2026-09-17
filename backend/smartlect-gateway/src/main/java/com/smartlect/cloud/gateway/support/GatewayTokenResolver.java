package com.smartlect.cloud.gateway.support;

import org.springframework.http.HttpCookie;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ServerWebExchange;

public final class GatewayTokenResolver {

    public static final String TOKEN_WEB = "token";
    public static final String TOKEN_ADMIN = "adminToken";

    private GatewayTokenResolver() {
    }

    public static String resolveWebToken(ServerWebExchange exchange) {
        return resolveToken(exchange, TOKEN_WEB);
    }

    public static String resolveAdminToken(ServerWebExchange exchange) {
        return resolveToken(exchange, TOKEN_ADMIN);
    }

    private static String resolveToken(ServerWebExchange exchange, String cookieName) {
        ServerHttpRequest request = exchange.getRequest();
        String cookie = cookieValue(request, cookieName);
        if (StringUtils.hasText(cookie)) {
            return cookie;
        }
        String authorization = request.getHeaders().getFirst("Authorization");
        if (StringUtils.hasText(authorization) && authorization.regionMatches(true, 0, "Bearer ", 0, 7)) {
            String bearer = authorization.substring(7).trim();
            return StringUtils.hasText(bearer) ? bearer : null;
        }
        return null;
    }

    private static String cookieValue(ServerHttpRequest request, String name) {
        MultiValueMap<String, HttpCookie> cookies = request.getCookies();
        if (cookies == null || cookies.isEmpty()) {
            return null;
        }
        HttpCookie cookie = cookies.getFirst(name);
        if (cookie == null || !StringUtils.hasText(cookie.getValue())) {
            return null;
        }
        return cookie.getValue().trim();
    }
}
