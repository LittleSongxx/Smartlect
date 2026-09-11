package com.smartlect.biz;

import com.smartlect.api.vo.SignRecordSyncResultVO;

public interface SignRecordSyncService {

    void ensureHashHydrated(String userId);

    boolean syncUserFromDb(String userId, boolean force);

    SignRecordSyncResultVO syncAllFromDb(boolean force);

    void warmUpMissingOnStartup();
}
