package com.smartlect.biz;

import com.smartlect.entity.po.SensitiveWord;
import com.smartlect.entity.query.SensitiveWordQuery;
import com.smartlect.entity.vo.PaginationResultVO;

public interface SensitiveWordService {

    PaginationResultVO<SensitiveWord> findListByPage(SensitiveWordQuery query);

    void save(Long id, String word, String replaceWord, Integer status);

    void delete(Long id);

    void refreshCache();

    int syncFromDbToRedis();
}
