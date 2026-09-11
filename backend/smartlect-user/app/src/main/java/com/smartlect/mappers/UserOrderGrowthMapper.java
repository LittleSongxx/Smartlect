package com.smartlect.mappers;

import com.smartlect.entity.po.UserOrderGrowth;
import org.apache.ibatis.annotations.Param;

public interface UserOrderGrowthMapper {

    Integer insert(@Param("bean") UserOrderGrowth bean);

    UserOrderGrowth selectByOrderId(@Param("orderId") String orderId);
}
