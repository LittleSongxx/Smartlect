package com.smartlect.mappers;

import org.apache.ibatis.annotations.Param;

/**
 * 签到权威位图。setBitIfMissing 的 (bits &amp; mask)=0 条件让“同日重复签到”在
 * 数据库层表现为 0 行影响——这是 Redis 丢失或并发竞争下的最终幂等屏障。
 */
public interface SignBitmapMapper {

    int insertBitIfAbsent(@Param("userId") String userId, @Param("yearMonth") String yearMonth,
                          @Param("mask") int mask);

    int setBitIfMissing(@Param("userId") String userId, @Param("yearMonth") String yearMonth,
                        @Param("mask") int mask);

    Integer totalSignDays(@Param("userId") String userId);
}
