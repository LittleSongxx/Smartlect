package com.smartlect.controller.admin;

import com.smartlect.entity.query.OrderCommentQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.OrderCommentService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("adminOrderCommentController")
@RequestMapping("/admin/orderComment")
public class OrderCommentController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private OrderCommentService orderCommentService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(OrderCommentQuery query){
		return getSuccessResponseVO(orderCommentService.findListByPage(query));
	}

	@PostMapping("/getOrderCommentByOrderId")
	public ResponseVO getOrderCommentByOrderId(String orderId) {
		return getSuccessResponseVO(orderCommentService.getOrderCommentByOrderId(orderId));
	}

}
