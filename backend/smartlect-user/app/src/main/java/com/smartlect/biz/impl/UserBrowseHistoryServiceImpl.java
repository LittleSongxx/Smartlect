package com.smartlect.biz.impl;

import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.support.ProductFeignSupport;
import com.smartlect.api.vo.ProductInfoSnapshotVO;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.api.dto.BrowseHistoryMessageDTO;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.po.UserBrowseHistory;
import com.smartlect.entity.query.SimplePage;
import com.smartlect.entity.query.UserBrowseHistoryQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.UserBrowseProductVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.mappers.UserBrowseHistoryMapper;
import com.smartlect.biz.UserBrowseHistoryService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service("userBrowseHistoryService")
@Slf4j
public class UserBrowseHistoryServiceImpl implements UserBrowseHistoryService {

    @Resource
    private UserBrowseHistoryMapper<UserBrowseHistory, UserBrowseHistoryQuery> userBrowseHistoryMapper;
    @Resource
    private ProductFeignSupport productFeignSupport;
    @Resource
    private RedisComponent redisComponent;
    @Resource
    private ReliableMessageSender reliableMessageSender;
    @Resource
    private CommerceOutcomeClient commerceOutcomeClient;

    @Override
    public void enqueueRecordBrowse(String userId, String productId) {
        if (StringTools.isEmpty(userId) || StringTools.isEmpty(productId)) {
            return;
        }
        redisComponent.recordBrowseRecent(userId, productId);
        BrowseHistoryMessageDTO message = new BrowseHistoryMessageDTO();
        message.setUserId(userId);
        message.setProductId(productId);
        long browseTime = System.currentTimeMillis();
        message.setBrowseTime(browseTime);
        reliableMessageSender.sendMessage(
                RabbitMQConfig.BROWSE_EXCHANGE,
                RabbitMQConfig.BROWSE_RECORD_KEY,
                message,
                MqIdempotencyKeys.browseRecord(userId, productId, browseTime),
                MessageReliabilityLevelEnum.HIGH);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void recordBrowse(String userId, String productId) {
        recordBrowse(userId, productId, null);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void recordBrowse(String userId, String productId, Long browseTime) {
        if (StringTools.isEmpty(userId) || StringTools.isEmpty(productId)) {
            return;
        }
        if (browseTime != null && (browseTime <= 0 || browseTime > System.currentTimeMillis() + 60_000)) {
            throw new BusinessException("无效的浏览发生时间");
        }
        Date occurredAt = browseTime == null ? new Date() : new Date(browseTime);
        userBrowseHistoryMapper.recordLatest(userId, productId, occurredAt);
        // Old messages with no producer timestamp can update history, but cannot
        // invent an occurredAt for a new Growth fact.
        if (browseTime == null) return;
        commerceOutcomeClient.recordV2AfterCommit(new CommerceOutcomeClient.OutcomeEvent(
                CommerceOutcomeClient.stableEventId("view", userId, productId, browseTime),
                "PRODUCT_BROWSE", CommerceOutcomeClient.stableIdempotencyKey("view", userId, productId, browseTime),
                "VIEW", userId, null, productId, null, null, null,
                Map.of("executionScopeId", "store"), occurredAt.toInstant().toString()));
    }

    @Override
    public PaginationResultVO<UserBrowseProductVO> loadBrowsePage(String userId, Integer pageNo) {
        UserBrowseHistoryQuery query = new UserBrowseHistoryQuery();
        query.setUserId(userId);
        query.setPageNo(pageNo);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("browse_time desc"));
        int count = userBrowseHistoryMapper.selectCount(query);
        int pageSize = PageSize.SIZE15.getSize();
        SimplePage page = new SimplePage(pageNo, count, pageSize);
        query.setSimplePage(page);
        List<UserBrowseHistory> histories = userBrowseHistoryMapper.selectList(query);
        List<UserBrowseProductVO> voList = new ArrayList<>();
        if (!histories.isEmpty()) {
            List<String> productIds = histories.stream().map(UserBrowseHistory::getProductId).collect(Collectors.toList());
            ProductSnapshotBatchVO batch = productFeignSupport.snapshotBatch(productIds);
            Map<String, ProductInfoSnapshotVO> productMap = productFeignSupport.toProductInfoMap(batch);
            for (UserBrowseHistory history : histories) {
                UserBrowseProductVO vo = new UserBrowseProductVO();
                vo.setHistoryId(history.getHistoryId());
                vo.setProductId(history.getProductId());
                vo.setBrowseTime(history.getBrowseTime());
                ProductInfoSnapshotVO product = productMap.get(history.getProductId());
                if (product != null) {
                    vo.setProductName(product.getProductName());
                    vo.setCover(resolveCover(product.getCover()));
                    vo.setStatus(product.getStatus());
                    vo.setMinPrice(product.getMinPrice());
                }
                voList.add(vo);
            }
        }
        return new PaginationResultVO<>(count, page.getPageSize(), page.getPageNo(), page.getPageTotal(), voList);
    }

    @Override
    public void clearBrowse(String userId) {
        UserBrowseHistoryQuery query = new UserBrowseHistoryQuery();
        query.setUserId(userId);
        userBrowseHistoryMapper.deleteByParam(query);
    }

    @Override
    public void removeBrowse(String userId, Long historyId) {
        UserBrowseHistory history = userBrowseHistoryMapper.selectByHistoryId(historyId);
        if (history == null || !history.getUserId().equals(userId)) {
            throw new BusinessException("记录不存在");
        }
        userBrowseHistoryMapper.deleteByHistoryId(historyId);
    }

    private String resolveCover(String cover) {
        if (StringTools.isEmpty(cover)) {
            return cover;
        }
        if (cover.contains(",")) {
            return cover.split(",")[0];
        }
        return cover;
    }
}
