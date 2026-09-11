package com.smartlect.service;

import com.smartlect.entity.dto.MqCompensationRecord;
import com.smartlect.entity.po.MqCompensationLog;
import com.smartlect.entity.query.MqCompensationLogQuery;
import com.smartlect.entity.vo.PaginationResultVO;

public interface MqCompensationLogService {

    PaginationResultVO<MqCompensationLog> findListByPage(MqCompensationLogQuery query);

    MqCompensationLog getByLogId(Integer logId);

    void saveFromFailure(MqCompensationRecord record);

    void updateHandleStatus(Integer logId, Integer status, String handleRemark);

    void replay(Integer logId);

    int autoReplayPendingSendFailures(int batchSize, int maxRetryCount);
}
