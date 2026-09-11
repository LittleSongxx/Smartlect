package com.smartlect.mappers;

import com.smartlect.entity.po.SensitiveWord;
import org.apache.ibatis.annotations.Param;

public interface SensitiveWordMapper<T, P> extends BaseMapper<T, P> {

    SensitiveWord selectByWord(@Param("word") String word);

    Integer deleteById(@Param("id") Long id);
}
