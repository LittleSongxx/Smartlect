package com.smartlect.biz.impl;

import java.util.List;

import jakarta.annotation.Resource;

import org.springframework.stereotype.Service;

import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.query.OrderLogisticsInfoRecordQuery;
import com.smartlect.entity.po.OrderLogisticsInfoRecord;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.mappers.OrderLogisticsInfoRecordMapper;
import com.smartlect.biz.OrderLogisticsInfoRecordService;
import com.smartlect.utils.StringTools;
import com.smartlect.utils.PageUtils;

@Service("orderLogisticsInfoRecordService")
public class OrderLogisticsInfoRecordServiceImpl implements OrderLogisticsInfoRecordService {

	@Resource
	private OrderLogisticsInfoRecordMapper<OrderLogisticsInfoRecord, OrderLogisticsInfoRecordQuery> orderLogisticsInfoRecordMapper;

	@Override
	public List<OrderLogisticsInfoRecord> findListByParam(OrderLogisticsInfoRecordQuery param) {
		return this.orderLogisticsInfoRecordMapper.selectList(param);
	}

	@Override
	public Integer findCountByParam(OrderLogisticsInfoRecordQuery param) {
		return this.orderLogisticsInfoRecordMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<OrderLogisticsInfoRecord> findListByPage(OrderLogisticsInfoRecordQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(OrderLogisticsInfoRecord bean) {
		return this.orderLogisticsInfoRecordMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<OrderLogisticsInfoRecord> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderLogisticsInfoRecordMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<OrderLogisticsInfoRecord> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderLogisticsInfoRecordMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(OrderLogisticsInfoRecord bean, OrderLogisticsInfoRecordQuery param) {
		StringTools.checkParam(param);
		return this.orderLogisticsInfoRecordMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(OrderLogisticsInfoRecordQuery param) {
		StringTools.checkParam(param);
		return this.orderLogisticsInfoRecordMapper.deleteByParam(param);
	}

	@Override
	public OrderLogisticsInfoRecord getOrderLogisticsInfoRecordByRecordId(Integer recordId) {
		return this.orderLogisticsInfoRecordMapper.selectByRecordId(recordId);
	}

	@Override
	public Integer updateOrderLogisticsInfoRecordByRecordId(OrderLogisticsInfoRecord bean, Integer recordId) {
		return this.orderLogisticsInfoRecordMapper.updateByRecordId(bean, recordId);
	}

	@Override
	public Integer deleteOrderLogisticsInfoRecordByRecordId(Integer recordId) {
		return this.orderLogisticsInfoRecordMapper.deleteByRecordId(recordId);
	}
}
