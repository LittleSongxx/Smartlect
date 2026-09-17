package com.smartlect.controller.admin;

import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.security.TrialOrderPrivacy;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("orderInfoController")
@RequestMapping("/admin/orderInfo")
public class OrderInfoController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private OrderInfoService orderInfoService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(OrderInfoQuery query){
		return getSuccessResponseVO(TrialOrderPrivacy.redact(orderInfoService.findListByPage(query)));
	}

	@PostMapping("/getOrderInfoByOrderId")
	public ResponseVO getOrderInfoByOrderId(String orderId) {
		return getSuccessResponseVO(TrialOrderPrivacy.redact(orderInfoService.getOrderInfoByOrderId(orderId)));
	}

}
