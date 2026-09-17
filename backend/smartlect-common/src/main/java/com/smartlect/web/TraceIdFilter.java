package com.smartlect.web;

import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.utils.StringTools;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class TraceIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String w3cTraceId = W3cTraceContext.traceIdFromTraceparent(request.getHeader(W3cTraceContext.TRACEPARENT));
        String correlationId;
        if (w3cTraceId != null) {
            correlationId = w3cTraceId;
        } else if (!StringTools.isEmpty(request.getHeader(InternalApiHeaders.TRACE_ID))) {
            correlationId = request.getHeader(InternalApiHeaders.TRACE_ID);
        } else {
            // 日志关联，不是 OTEL trace_id，也不伪造 traceparent。
            correlationId = UUID.randomUUID().toString().replace("-", "");
        }
        MDC.put(InternalApiHeaders.TRACE_ID_MDC, correlationId);
        response.setHeader(InternalApiHeaders.TRACE_ID, correlationId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(InternalApiHeaders.TRACE_ID_MDC);
        }
    }
}
