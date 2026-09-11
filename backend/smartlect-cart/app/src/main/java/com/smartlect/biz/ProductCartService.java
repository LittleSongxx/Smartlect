package com.smartlect.biz;

import java.util.List;

import com.smartlect.entity.query.ProductCartQuery;
import com.smartlect.entity.po.ProductCart;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductCartVO;
import jakarta.validation.constraints.NotEmpty;

public interface ProductCartService {

	List<ProductCart> findListByParam(ProductCartQuery param);

	Integer findCountByParam(ProductCartQuery param);

	PaginationResultVO<ProductCart> findListByPage(ProductCartQuery param);

	Integer add(ProductCart bean);

	Integer addBatch(List<ProductCart> listBean);

	Integer addOrUpdateBatch(List<ProductCart> listBean);

	Integer updateByParam(ProductCart bean,ProductCartQuery param);

	Integer deleteByParam(ProductCartQuery param);

	ProductCart getProductCartByCartId(String cartId);

	Integer updateProductCartByCartId(ProductCart bean,String cartId);

	Integer deleteProductCartByCartId(String cartId);

	ProductCart getProductCartByProductIdAndPropertyValueIdHashAndUserId(String productId,String propertyValueIdHash,String userId);

	Integer updateProductCartByProductIdAndPropertyValueIdHashAndUserId(ProductCart bean,String productId,String propertyValueIdHash,String userId);

	Integer deleteProductCartByProductIdAndPropertyValueIdHashAndUserId(String productId,String propertyValueIdHash,String userId);

    ProductCart add2Cart(@NotEmpty ProductCart productCart);

	PaginationResultVO<ProductCartVO> findListByPageAndUserId(@NotEmpty ProductCartQuery param, @NotEmpty String userId);
}
