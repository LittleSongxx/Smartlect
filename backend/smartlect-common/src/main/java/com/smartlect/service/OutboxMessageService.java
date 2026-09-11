package com.smartlect.service;

import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.LocalMessageOutbox;

import java.util.List;

public interface OutboxMessageService {

    Long savePending(String exchange, String routingKey, Object payload,
                     String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel);

    void tryDispatch(Long id);

    int dispatchPendingBatch(int batchSize, int maxRetries);

    int countExhausted();

    List<LocalMessageOutbox> listExhausted(int limit);

    boolean replayExhausted(Long id);
}
