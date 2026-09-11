package com.smartlect.biz;

import java.util.List;

import com.smartlect.entity.query.StatisticsInfoQuery;
import com.smartlect.entity.po.StatisticsInfo;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.StatisticsDataVO;
import com.smartlect.entity.vo.TodayDataVO;

public interface StatisticsInfoService {

	PaginationResultVO<StatisticsInfo> findListByPage(StatisticsInfoQuery param);

	List<TodayDataVO> getTodayData();

	List<StatisticsDataVO> loadWeeklyStatisticsData();

	void statistics(String startTime, String endTime);
}
