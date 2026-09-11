package com.smartlect.mappers;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Insert;

import java.util.Date;

public interface UserBrowseHistoryMapper<T,P> extends BaseMapper<T,P> {

    @Insert("INSERT INTO user_browse_history(user_id,product_id,browse_time) VALUES(#{userId},#{productId},#{browseTime}) "
            + "ON DUPLICATE KEY UPDATE browse_time=GREATEST(browse_time,#{browseTime})")
    int recordLatest(@Param("userId") String userId, @Param("productId") String productId,
                     @Param("browseTime") Date browseTime);

	Integer updateByHistoryId(@Param("bean") T t, @Param("historyId") Long historyId);
	Integer deleteByHistoryId(@Param("historyId") Long historyId);
	T selectByHistoryId(@Param("historyId") Long historyId);

}
