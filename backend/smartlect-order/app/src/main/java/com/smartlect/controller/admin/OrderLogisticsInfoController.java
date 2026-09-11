package com.smartlect.controller.admin;

import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderLogisticsInfoService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("orderLogisticsInfoController")
@RequestMapping("/admin/orderLogisticsInfo")
public class OrderLogisticsInfoController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private OrderLogisticsInfoService orderLogisticsInfoService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(OrderLogisticsInfoQuery query){
		return getSuccessResponseVO(orderLogisticsInfoService.findListByPage(query));
	}

	@PostMapping("/getOrderLogisticsInfoByOrderId")
	public ResponseVO getOrderLogisticsInfoByOrderId(String orderId) {
		return getSuccessResponseVO(orderLogisticsInfoService.getOrderLogisticsInfoByOrderId(orderId));
	}

}
