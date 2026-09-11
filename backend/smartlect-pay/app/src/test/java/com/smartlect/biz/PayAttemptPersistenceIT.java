package com.smartlect.biz;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.service.OutboxMessageService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Real MySQL intent locks and transactional attempt/Outbox writes; transport is explicitly mocked. */
@Testcontainers
class PayAttemptPersistenceIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_pay_test").withUsername("smartlect_test").withPassword("test-only");
    DriverManagerDataSource datasource;
    JdbcTemplate jdbc;
    OutboxMessageService outbox;
    CommerceOutcomeClient outcomes;
    PayAttemptService attempts;

    @BeforeEach
    void setUp() throws Exception {
        datasource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(datasource).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(datasource);
        jdbc.update("DELETE FROM pay_payment_attempt");
        jdbc.update("DELETE FROM local_message_outbox");
        jdbc.update("DELETE FROM pay_mock_refund");
        jdbc.update("DELETE FROM pay_trade_record");
        for (int number : List.of(1, 2)) {
            jdbc.update("INSERT INTO pay_trade_record (trade_id,order_id,user_id,pay_order_id,pay_channel,pay_amount,trade_status,create_time) "
                    + "VALUES (?,?,?,?,?,90.00,0,NOW())", "trade-" + number, "order-" + number, "owner-1", "pay-" + number, "mock");
        }
        outbox = mock(OutboxMessageService.class);
        when(outbox.savePending(anyString(), anyString(), any(), anyString(), any())).thenAnswer(call -> {
            jdbc.update("INSERT INTO local_message_outbox (idempotency_key,exchange_name,routing_key,payload_json,create_time) "
                    + "VALUES (?,?,?,?,NOW())", call.getArgument(3), call.getArgument(0), call.getArgument(1),
                    new ObjectMapper().writeValueAsString(call.getArgument(2, Object.class)));
            return jdbc.queryForObject("SELECT id FROM local_message_outbox WHERE idempotency_key=?", Long.class, call.getArgument(3, String.class));
        });
        TransactionalMqSender sender = new TransactionalMqSender();
        ReflectionTestUtils.setField(sender, "outboxMessageService", outbox);
        outcomes = new CommerceOutcomeClient(sender, true);
        attempts = reconstructed();
    }

    private PayAttemptService reconstructed() {
        ProxyFactory proxy = new ProxyFactory(new PayAttemptService(jdbc, outcomes));
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(datasource),
                new AnnotationTransactionAttributeSource()));
        return (PayAttemptService) proxy.getProxy();
    }

    @Test
    void concurrent_replay_and_restart_keep_original_time_and_single_outbox() throws Exception {
        var request = new PayAttemptService.Request("same-attempt", "pay-1");
        var executor = Executors.newFixedThreadPool(4);
        PayAttemptService.Attempt first;
        try {
            var results = executor.invokeAll(List.<Callable<PayAttemptService.Attempt>>of(
                    () -> attempts.decline("owner-1", request), () -> attempts.decline("owner-1", request),
                    () -> attempts.decline("owner-1", request), () -> attempts.decline("owner-1", request)));
            first = results.get(0).get();
            for (var result : results) assertEquals(first, result.get());
        } finally {
            executor.shutdownNow();
        }
        assertEquals(1, count("pay_payment_attempt"));
        assertEquals(1, count("local_message_outbox"));
        assertEquals(0, jdbc.queryForObject("SELECT CAST(trade_status AS SIGNED) FROM pay_trade_record WHERE pay_order_id='pay-1'", Integer.class));
        jdbc.update("UPDATE pay_trade_record SET trade_status=1 WHERE pay_order_id='pay-1'");
        assertEquals(first, reconstructed().decline("owner-1", request));
        assertEquals(first, reconstructed().get("owner-1", request));
        var batch = new ObjectMapper().readTree(jdbc.queryForObject("SELECT payload_json FROM local_message_outbox", String.class));
        assertEquals(2, batch.get("schema_version").intValue());
        var event = batch.get("events").get(0);
        assertEquals(first.eventId(), event.get("eventId").textValue());
        assertEquals(first.occurredAt(), event.get("occurredAt").textValue());
        assertEquals("PAYMENT_ATTEMPT", event.get("eventType").textValue());
        assertEquals("mock", event.get("payload").get("paymentMode").textValue());
        assertFalse(event.get("payload").has("paidAmount"));
        assertEquals(9000, event.get("payload").get("attemptedAmountCents").longValue());
        verify(outbox, times(1)).tryDispatch(anyLong());
    }

    @Test
    void event_failure_rolls_back_attempt_and_retry_creates_one_fact() {
        var broken = mock(CommerceOutcomeClient.class);
        doThrow(new IllegalStateException("injected outbox failure")).when(broken).recordV2AfterCommit(any());
        outcomes = broken;
        var request = new PayAttemptService.Request("retry-attempt", "pay-1");
        assertThrows(IllegalStateException.class, () -> reconstructed().decline("owner-1", request));
        assertEquals(0, count("pay_payment_attempt"));
        assertEquals(0, count("local_message_outbox"));
        assertEquals(0, jdbc.queryForObject("SELECT CAST(trade_status AS SIGNED) FROM pay_trade_record WHERE pay_order_id='pay-1'", Integer.class));
        // Restore the normal executor retained by the originally constructed proxy.
        attempts.decline("owner-1", request);
        assertEquals(1, count("pay_payment_attempt"));
        assertEquals(1, count("local_message_outbox"));
    }

    @Test
    void owner_idempotency_and_intent_state_checks_leave_no_false_failure() {
        var original = new PayAttemptService.Request("attempt", "pay-1");
        attempts.decline("owner-1", original);
        assertEquals(403, assertThrows(HttpBusinessException.class, () -> attempts.get("other", original)).getHttpStatus());
        assertEquals(403, assertThrows(HttpBusinessException.class, () -> attempts.decline("other", original)).getHttpStatus());
        assertEquals(409, assertThrows(HttpBusinessException.class, () -> attempts.decline("owner-1",
                new PayAttemptService.Request("attempt", "pay-2"))).getHttpStatus());
        for (int status : List.of(1, 2, 3)) {
            jdbc.update("UPDATE pay_trade_record SET trade_status=? WHERE pay_order_id='pay-2'", status);
            assertEquals(409, assertThrows(HttpBusinessException.class, () -> attempts.decline("owner-1",
                    new PayAttemptService.Request("new-" + status, "pay-2"))).getHttpStatus());
        }
        jdbc.update("UPDATE pay_trade_record SET trade_status=0,pay_channel='alipay_pc' WHERE pay_order_id='pay-2'");
        assertEquals(403, assertThrows(HttpBusinessException.class, () -> attempts.decline("owner-1",
                new PayAttemptService.Request("real-channel", "pay-2"))).getHttpStatus());
        assertEquals(1, count("pay_payment_attempt"));
        assertEquals(1, count("local_message_outbox"));
    }

    private int count(String table) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
    }
}
