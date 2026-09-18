package com.smartlect.compensation;

/**
 * 知识投影入队的失败补偿通道：商品保存后的 PRODUCT_AUTO 投影 enqueue 连续失败时
 * 落 mq_compensation_log，重放由此端口重新发起 HTTP 入队。
 */
public interface ProductProjectionCompensatePort {

    void replayProjectionEnqueue(String productId);
}
