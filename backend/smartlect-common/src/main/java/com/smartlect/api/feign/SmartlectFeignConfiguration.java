package com.smartlect.api.feign;

import feign.Request;
import feign.RequestInterceptor;
import feign.codec.ErrorDecoder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;

import java.util.concurrent.TimeUnit;

public class SmartlectFeignConfiguration {

    @Bean
    public Request.Options feignRequestOptions(
            @Value("${smartlect.feign.connect-timeout-ms:3000}") int connectTimeoutMs,
            @Value("${smartlect.feign.read-timeout-ms:10000}") int readTimeoutMs) {
        return new Request.Options(
                connectTimeoutMs, TimeUnit.MILLISECONDS,
                readTimeoutMs, TimeUnit.MILLISECONDS,
                true);
    }

    @Bean
    public ErrorDecoder smartlectFeignErrorDecoder() {
        return new SmartlectFeignErrorDecoder();
    }

    @Bean
    public RequestInterceptor feignInternalAuthInterceptor(
            @Value("${smartlect.internal.token:}") String internalToken) {
        return new FeignInternalAuthInterceptor(internalToken);
    }

    @Bean
    public RequestInterceptor feignTraceInterceptor() {
        return new FeignTraceInterceptor();
    }
}
