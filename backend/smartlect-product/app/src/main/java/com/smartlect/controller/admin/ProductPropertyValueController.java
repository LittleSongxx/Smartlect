package com.smartlect.controller.admin;

import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.ProductPropertyValueService;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController("productPropertyValueController")
@RequestMapping("/admin/productPropertyValue")
public class ProductPropertyValueController extends com.smartlect.controller.admin.ABaseController{

	@Resource
	private ProductPropertyValueService productPropertyValueService;

	@PostMapping("/loadDataList")
	public ResponseVO loadDataList(ProductPropertyValueQuery query){
		return getSuccessResponseVO(productPropertyValueService.findListByPage(query));
	}

	@PostMapping("/getProductPropertyValueByProductIdAndPropertyValueId")
	public ResponseVO getProductPropertyValueByProductIdAndPropertyValueId(String productId,String propertyValueId) {
		return getSuccessResponseVO(productPropertyValueService.getProductPropertyValueByProductIdAndPropertyValueId(productId,propertyValueId));
	}

}
