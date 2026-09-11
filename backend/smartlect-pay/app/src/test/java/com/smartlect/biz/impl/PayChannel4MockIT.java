package com.smartlect.biz.impl;

import com.smartlect.api.support.OrderFeignSupport;
import com.smartlect.biz.PayTradeRecordService;
import com.smartlect.entity.po.PayTradeRecord;
import com.smartlect.exception.BusinessException;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/** Real MySQL constraints/transactions; this dedicated container owns all test data. */
@Testcontainers
class PayChannel4MockIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_pay_test").withUsername("smartlect_test").withPassword("test-only");
    JdbcTemplate jdbc;
    PayChannel4Mock channel;

    @BeforeEach
    void setUp() {
        var datasource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(datasource).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(datasource);
        jdbc.update("DELETE FROM pay_mock_refund");
        jdbc.update("DELETE FROM pay_trade_record");
        jdbc.update("INSERT INTO pay_trade_record (trade_id, order_id, user_id, pay_order_id, pay_channel, pay_amount, trade_status, create_time) "
                + "VALUES ('trade-1', 'order-1', 'owner-1', 'pay-1', 'mock', 90.00, 1, NOW())");
        PayTradeRecordService trades = mock(PayTradeRecordService.class);
        when(trades.findByPayOrderId(anyString())).thenAnswer(call -> jdbc.queryForObject(
                "SELECT * FROM pay_trade_record WHERE pay_order_id = ?", (row, index) -> {
                    PayTradeRecord record = new PayTradeRecord();
                    record.setPayOrderId(row.getString("pay_order_id"));
                    record.setUserId(row.getString("user_id"));
                    record.setPayChannel(row.getString("pay_channel"));
                    record.setPayAmount(row.getBigDecimal("pay_amount"));
                    record.setTradeStatus(row.getInt("trade_status"));
                    return record;
                }, call.getArgument(0, String.class)));
        doAnswer(call -> jdbc.update("UPDATE pay_trade_record SET trade_status = 3 WHERE pay_order_id = ?",
                call.getArgument(0, String.class))).when(trades).markRefunded(anyString());
        ProxyFactory proxy = new ProxyFactory(new PayChannel4Mock(trades, mock(OrderFeignSupport.class), jdbc));
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(datasource),
                new AnnotationTransactionAttributeSource()));
        channel = (PayChannel4Mock) proxy.getProxy();
    }

    @Test
    void refundsPersistReplayAndCannotExceedActualPayment() {
        channel.refund("pay-1", "refund-1", new BigDecimal("30.00"));
        assertThrows(BusinessException.class, () -> channel.refund("pay-1", "refund-1", new BigDecimal("31.00")));
        channel.refund("pay-1", "refund-2", new BigDecimal("60.00"));
        channel.refund("pay-1", "refund-2", new BigDecimal("60.00"));
        assertThrows(BusinessException.class, () -> channel.refund("pay-1", "refund-3", BigDecimal.ONE));
        assertEquals(2, jdbc.queryForObject("SELECT COUNT(*) FROM pay_mock_refund", Integer.class));
        assertEquals(new BigDecimal("90.00"), jdbc.queryForObject("SELECT SUM(refund_amount) FROM pay_mock_refund", BigDecimal.class));
        assertEquals(3, jdbc.queryForObject("SELECT trade_status FROM pay_trade_record WHERE pay_order_id='pay-1'", Integer.class));
    }

    @Test
    void concurrentDifferentRefundIdsCannotOverspendTheSamePayment() throws Exception {
        var executor = Executors.newFixedThreadPool(2);
        try {
            var tasks = List.<Callable<Boolean>>of(
                    () -> tryRefund("parallel-1"), () -> tryRefund("parallel-2"));
            var results = executor.invokeAll(tasks);
            assertNotEquals(results.get(0).get(), results.get(1).get());
            assertEquals(new BigDecimal("60.00"), jdbc.queryForObject("SELECT SUM(refund_amount) FROM pay_mock_refund", BigDecimal.class));
            assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM pay_mock_refund", Integer.class));
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void unpaidPaymentAndFractionalCentRefundsLeaveNoSettlement() {
        jdbc.update("UPDATE pay_trade_record SET trade_status=0");
        assertThrows(BusinessException.class, () -> channel.refund("pay-1", "refund-1", BigDecimal.ONE));
        assertThrows(BusinessException.class, () -> channel.refund("pay-1", "refund-2", new BigDecimal("0.001")));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM pay_mock_refund", Integer.class));
    }

    private boolean tryRefund(String id) {
        try {
            channel.refund("pay-1", id, new BigDecimal("60.00"));
            return true;
        } catch (BusinessException rejected) {
            return false;
        }
    }
}
