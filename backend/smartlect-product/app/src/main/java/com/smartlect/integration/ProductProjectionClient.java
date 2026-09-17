package com.smartlect.integration;

import com.smartlect.constants.InternalApiHeaders;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.client.RestClient;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Fire-and-forget enqueue of PRODUCT_AUTO projection. Product save/shelf must
 * never wait on Growth or indexing.
 */
@Component
public class ProductProjectionClient {

    private static final Logger log = LoggerFactory.getLogger(ProductProjectionClient.class);

    private final RestClient client;
    private final String internalToken;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(thread -> {
        Thread worker = new Thread(thread, "product-projection-enqueue");
        worker.setDaemon(true);
        return worker;
    });

    public ProductProjectionClient(
            RestClient.Builder builder,
            @Value("${smartlect.growth.base-url:http://127.0.0.1:18000}") String growthBaseUrl,
            @Value("${smartlect.internal.token:}") String internalToken,
            @Value("${smartlect.growth.projection-connect-timeout-ms:200}") int connectTimeoutMs,
            @Value("${smartlect.growth.projection-read-timeout-ms:800}") int readTimeoutMs) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofMillis(Math.max(connectTimeoutMs, 50)));
        requestFactory.setReadTimeout(Duration.ofMillis(Math.max(readTimeoutMs, 50)));
        this.client = builder.clone()
                .baseUrl(growthBaseUrl.replaceAll("/+$", ""))
                .requestFactory(requestFactory)
                .build();
        this.internalToken = internalToken == null ? "" : internalToken;
    }

    public void enqueueAfterCommit(String productId) {
        if (productId == null || productId.isBlank()) {
            return;
        }
        String id = productId.trim();
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            enqueueAsync(id);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                enqueueAsync(id);
            }
        });
    }

    void enqueueAsync(String productId) {
        executor.execute(() -> enqueueQuietly(productId));
    }

    void enqueueQuietly(String productId) {
        if (internalToken.isBlank()) {
            log.error("product_projection_skipped product_id={} reason=internal_token_missing", productId);
            return;
        }
        Exception last = null;
        for (int attempt = 1; attempt <= 3; attempt++) {
            try {
                client.post()
                        .uri("/internal/product-projection/enqueue")
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(InternalApiHeaders.INTERNAL_TOKEN, internalToken)
                        .body(Map.of("product_id", productId, "execution_scope_id", "store"))
                        .retrieve()
                        .toBodilessEntity();
                log.info("product_projection_enqueued product_id={} attempt={}", productId, attempt);
                return;
            } catch (Exception error) {
                last = error;
                log.warn("product_projection_enqueue_failed product_id={} attempt={} error={}",
                        productId, attempt, error.getClass().getSimpleName());
            }
        }
        log.error("product_projection_enqueue_exhausted product_id={} error={}",
                productId, last == null ? "unknown" : last.getClass().getSimpleName());
    }
}
