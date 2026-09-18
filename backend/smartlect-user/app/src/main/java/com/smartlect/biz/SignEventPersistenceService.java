package com.smartlect.biz;

import com.smartlect.api.dto.SignRecordMessageDTO;
import com.smartlect.entity.po.UserSignRecord;
import com.smartlect.entity.po.UserSignRecordDetail;
import com.smartlect.entity.query.UserSignRecordDetailQuery;
import com.smartlect.entity.query.UserSignRecordQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.SignBitmapMapper;
import com.smartlect.mappers.UserSignRecordDetailMapper;
import com.smartlect.mappers.UserSignRecordMapper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;

@Service
public class SignEventPersistenceService {

    @Resource
    private UserSignRecordMapper<UserSignRecord, UserSignRecordQuery> userSignRecordMapper;
    @Resource
    private UserSignRecordDetailMapper<UserSignRecordDetail, UserSignRecordDetailQuery>
            userSignRecordDetailMapper;
    @Resource
    private SignBitmapMapper signBitmapMapper;
    @Resource
    private UserMemberProfileService userMemberProfileService;

    @Transactional(rollbackFor = Exception.class)
    public boolean persist(SignRecordMessageDTO message, int growthPoints) {
        if (message == null
                || StringTools.isEmpty(message.getUserId())
                || StringTools.isEmpty(message.getSignDate())
                || message.getSignDate().length() != 8
                || growthPoints <= 0) {
            throw new BusinessException("签到持久化参数不完整");
        }

        // 权威位图先占位：0 行即同日重复签到（DB 级幂等屏障，Redis 丢数据也拦得住）。
        if (!claimSignBit(message.getUserId(), message.getSignDate())) {
            return false;
        }

        UserSignRecordDetail detail = new UserSignRecordDetail();
        detail.setUserId(message.getUserId());
        detail.setSignDate(message.getSignDate());
        detail.setSignType(message.getSignType() == null ? 0 : message.getSignType());
        detail.setCreateTime(new Date());
        Integer inserted = userSignRecordDetailMapper.insertIgnore(detail);
        if (inserted == null || inserted != 1) {
            return false;
        }

        UserSignRecord record = new UserSignRecord();
        record.setUserId(message.getUserId());
        record.setContinuousDays(message.getContinuousDays());
        record.setTotalSignDays(message.getTotalSignDays());
        record.setUsedCount(message.getUsedCount());
        userSignRecordMapper.insertOrUpdate(record);
        userMemberProfileService.addGrowth(message.getUserId(), growthPoints);
        return true;
    }

    private boolean claimSignBit(String userId, String yyyyMMdd) {
        String yearMonth = yyyyMMdd.substring(0, 6);
        int day = Integer.parseInt(yyyyMMdd.substring(6, 8));
        int mask = 1 << (day - 1);
        if (signBitmapMapper.insertBitIfAbsent(userId, yearMonth, mask) == 1) {
            return true;
        }
        return signBitmapMapper.setBitIfMissing(userId, yearMonth, mask) == 1;
    }
}
