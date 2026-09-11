package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.support.OrderFeignSupport;
import com.smartlect.biz.PayChannel;
import com.smartlect.biz.PayTradeRecordService;
import com.smartlect.entity.po.PayTradeRecord;
import com.smartlect.exception.BusinessException;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.Map;
import java.util.Objects;

/** Simulated settlement against persisted Java payment intents; never contacts a provider. */
@Service("payChannel4Mock")
@ConditionalOnProperty(name = "smartlect.payment.mode", havingValue = "mock", matchIfMissing = true)
public class PayChannel4Mock implements PayChannel {
    private final PayTradeRecordService trades;
    private final OrderFeignSupport orders;
    private final JdbcTemplate jdbc;

    public PayChannel4Mock(PayTradeRecordService trades, OrderFeignSupport orders, JdbcTemplate jdbc) {
        this.trades = trades;
        this.orders = orders;
        this.jdbc = jdbc;
    }

    @Override
    public PayInfoDTO getPayUrl(PayChannelEnum channel, String payOrderId, String subject, BigDecimal amount) {
        PayTradeRecord record = requireIntent(payOrderId);
        if (!Objects.equals(record.getTradeStatus(), 0)) {
            throw new BusinessException("支付意图已完成或关闭");
        }
        // The supplied subject/amount are not settlement authority.
        PayInfoDTO result = new PayInfoDTO("smartlect-mock:" + record.getPayOrderId(),
                record.getPayOrderId(), record.getPayAmount());
        result.setOrderId(record.getOrderId());
        return result;
    }

    /** Commit the simulated charge before notifying order, so a lost response is replayable. */
    public PaymentResult completePayment(String payOrderId) {
        PayTradeRecord record = requireIntent(payOrderId);
        if (Objects.equals(record.getTradeStatus(), 2)) {
            throw new BusinessException("已关闭的支付意图不能付款");
        }
        if (Objects.equals(record.getTradeStatus(), 0)) {
            trades.markSuccess(record.getPayOrderId(), "smartlect-mock-" + record.getPayOrderId());
            record = requireIntent(record.getPayOrderId());
        }
        if (!Objects.equals(record.getTradeStatus(), 1) && !Objects.equals(record.getTradeStatus(), 3)) {
            throw new BusinessException("支付状态发生变化，请重新查询");
        }
        if (Objects.equals(record.getTradeStatus(), 1)) {
            // This existing order path owns payment events and is idempotent by payOrderId.
            orders.paySuccess(new PayOrderNotifyDTO(record.getPayOrderId(), record.getChannelOrderId()));
        }
        return new PaymentResult(record.getUserId(), record.getPayOrderId(), record.getPayAmount(),
                record.getChannelOrderId(), record.getTradeStatus());
    }

    @Override
    public PayOrderNotifyDTO payNotify(Map<String, String> requestParams, String jsonBody) {
        throw new BusinessException("模拟付款只能通过内部令牌保护的 complete 接口触发");
    }

    @Override
    public PayOrderNotifyDTO queryOrder(String payOrderId) {
        PayTradeRecord record = requireIntent(payOrderId);
        return Objects.equals(record.getTradeStatus(), 1) || Objects.equals(record.getTradeStatus(), 3)
                ? new PayOrderNotifyDTO(record.getPayOrderId(), record.getChannelOrderId()) : null;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void refund(String sourcePayOrderId, String refundOrderId, BigDecimal refundAmount) {
        requireId(sourcePayOrderId, 32);
        requireId(refundOrderId, 64);
        requireAmount(refundAmount);
        // Serializes different refund IDs for one payment; uniqueness handles replayed IDs.
        if (jdbc.queryForList("SELECT pay_order_id FROM pay_trade_record WHERE pay_order_id = ? FOR UPDATE",
                String.class, sourcePayOrderId).isEmpty()) {
            throw new BusinessException("支付意图不存在");
        }
        PayTradeRecord record = requireIntent(sourcePayOrderId);
        var previous = jdbc.query("SELECT source_pay_order_id, refund_amount FROM pay_mock_refund WHERE refund_order_id = ?",
                (row, index) -> new Refund(row.getString(1), row.getBigDecimal(2)), refundOrderId);
        if (!previous.isEmpty()) {
            Refund refund = previous.get(0);
            if (!record.getPayOrderId().equals(refund.sourcePayOrderId()) || refund.amount().compareTo(refundAmount) != 0) {
                throw new BusinessException("退款幂等标识与原请求不一致");
            }
            return;
        }
        if (!Objects.equals(record.getTradeStatus(), 1)) {
            throw new BusinessException("该支付意图没有剩余已付款项");
        }
        BigDecimal refunded = jdbc.queryForObject(
                "SELECT COALESCE(SUM(refund_amount), 0) FROM pay_mock_refund WHERE source_pay_order_id = ?",
                BigDecimal.class, record.getPayOrderId());
        BigDecimal total = refunded.add(refundAmount);
        if (total.compareTo(record.getPayAmount()) > 0) {
            throw new BusinessException("累计退款不能超过支付意图实付金额");
        }
        jdbc.update("INSERT INTO pay_mock_refund (refund_order_id, source_pay_order_id, refund_amount) VALUES (?, ?, ?)",
                refundOrderId, record.getPayOrderId(), refundAmount);
        if (total.compareTo(record.getPayAmount()) == 0) {
            trades.markRefunded(record.getPayOrderId());
        }
    }

    @Override
    public void closeOrder(String payOrderId) {
        PayTradeRecord record = requireIntent(payOrderId);
        if (Objects.equals(record.getTradeStatus(), 1) || Objects.equals(record.getTradeStatus(), 3)) {
            throw new BusinessException("已付款的支付意图不能关单");
        }
        trades.markClosed(record.getPayOrderId());
        if (!Objects.equals(requireIntent(record.getPayOrderId()).getTradeStatus(), 2)) {
            throw new BusinessException("付款与关单冲突，请重新查询支付状态");
        }
    }

    private PayTradeRecord requireIntent(String payOrderId) {
        requireId(payOrderId, 32);
        PayTradeRecord record = trades.findByPayOrderId(payOrderId);
        if (record == null || PayChannelEnum.resolve(record.getPayChannel()) != PayChannelEnum.MOCK) {
            throw new BusinessException("模拟支付意图不存在");
        }
        if (record.getUserId() == null || record.getUserId().isBlank()) {
            throw new BusinessException("支付意图缺少用户");
        }
        requireAmount(record.getPayAmount());
        return record;
    }

    private static void requireId(String value, int limit) {
        if (value == null || value.isBlank() || value.length() > limit) {
            throw new BusinessException("支付或退款标识无效");
        }
    }

    private static void requireAmount(BigDecimal amount) {
        if (amount == null || amount.signum() <= 0 || amount.stripTrailingZeros().scale() > 2) {
            throw new BusinessException("支付或退款金额必须为正整分");
        }
    }

    private record Refund(String sourcePayOrderId, BigDecimal amount) { }
    public record PaymentResult(String userId, String payOrderId, BigDecimal amount,
                                String channelOrderId, int tradeStatus) { }
}
