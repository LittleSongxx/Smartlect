package com.smartlect.biz;

import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.UserBrowseProductVO;

public interface UserBrowseHistoryService {

    void recordBrowse(String userId, String productId);

    void recordBrowse(String userId, String productId, Long browseTime);

    void enqueueRecordBrowse(String userId, String productId);

    PaginationResultVO<UserBrowseProductVO> loadBrowsePage(String userId, Integer pageNo);

    void clearBrowse(String userId);

    void removeBrowse(String userId, Long historyId);
}
