package com.smartlect.web;

import com.smartlect.constants.InternalApiHeaders;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class W3cTraceContextTest {

    private static final String SAMPLE =
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

    @Test
    void parsesOfficialTraceparent() {
        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736",
                W3cTraceContext.traceIdFromTraceparent(SAMPLE));
    }

    @Test
    void rejectsMissingOrZeroIds() {
        assertNull(W3cTraceContext.traceIdFromTraceparent(null));
        assertNull(W3cTraceContext.traceIdFromTraceparent("not-a-traceparent"));
        assertNull(W3cTraceContext.traceIdFromTraceparent(
                "00-00000000000000000000000000000000-00f067aa0ba902b7-01"));
    }

    @Test
    void filterPrefersTraceparentOverInventedUuid() throws Exception {
        TraceIdFilter filter = new TraceIdFilter();
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        FilterChain chain = mock(FilterChain.class);
        when(request.getHeader(W3cTraceContext.TRACEPARENT)).thenReturn(SAMPLE);
        AtomicReference<String> seen = new AtomicReference<>();
        doAnswer(invocation -> {
            seen.set(MDC.get(InternalApiHeaders.TRACE_ID_MDC));
            return null;
        }).when(chain).doFilter(request, response);

        filter.doFilterInternal(request, response, chain);

        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736", seen.get());
        verify(response).setHeader(InternalApiHeaders.TRACE_ID, "4bf92f3577b34da6a3ce929d0e0e4736");
        assertNull(MDC.get(InternalApiHeaders.TRACE_ID_MDC));
    }

    @Test
    void filterWithoutTraceparentUsesLogCorrelationNotTraceparent() throws Exception {
        TraceIdFilter filter = new TraceIdFilter();
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        FilterChain chain = mock(FilterChain.class);
        AtomicReference<String> seen = new AtomicReference<>();
        doAnswer(invocation -> {
            seen.set(MDC.get(InternalApiHeaders.TRACE_ID_MDC));
            return null;
        }).when(chain).doFilter(request, response);

        filter.doFilterInternal(request, response, chain);

        assertNotNull(seen.get());
        assertFalse(seen.get().contains("-"));
        assertEquals(32, seen.get().length());
        verify(response).setHeader(eq(InternalApiHeaders.TRACE_ID), eq(seen.get()));
    }
}
