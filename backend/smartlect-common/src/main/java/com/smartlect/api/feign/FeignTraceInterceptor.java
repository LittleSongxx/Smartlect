package com.smartlect.api.feign;

import com.smartlect.constants.InternalApiHeaders;
import feign.RequestInterceptor;
import feign.RequestTemplate;
import org.slf4j.MDC;
import org.springframework.util.StringUtils;

/**
 * 只转发 Filter 已回填的日志关联 ID。不发明 UUID，不手写 {@code traceparent}
 * （W3C 由可选 javaagent 注入，避免双埋）。
 */
public class FeignTraceInterceptor implements RequestInterceptor {

    @Override
    public void apply(RequestTemplate template) {
        String traceId = MDC.get(InternalApiHeaders.TRACE_ID_MDC);
        if (StringUtils.hasText(traceId)) {
            template.header(InternalApiHeaders.TRACE_ID, traceId);
        }
    }
}
