package com.smartlect.api.fallback;

import com.smartlect.api.ProductFeignClient;
import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.ProductIdListDTO;
import com.smartlect.api.dto.ProductSalesIncreaseDTO;
import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.api.vo.ProductSearchIndexVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductSkuListVO;
import com.smartlect.entity.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class ProductFeignFallbackFactory implements FallbackFactory<ProductFeignClient> {

    @Override
    public ProductFeignClient create(Throwable cause) {
        log.warn("Product Feign fallback: {}", cause == null ? "unknown" : cause.toString());
        return new ProductFeignClient() {
            @Override
            public ResponseVO<ProductSnapshotBatchVO> snapshotBatch(ProductIdListDTO dto) {
                return FeignFallbackResponses.unavailable("商品服务");
            }

            @Override
            public ResponseVO<ProductSkuSnapshotVO> defaultSku(ProductIdDTO dto) {
                return FeignFallbackResponses.unavailable("商品服务");
            }

            @Override
            public ResponseVO<Void> increaseSales(ProductSalesIncreaseDTO dto) {
                return FeignFallbackResponses.unavailable("商品服务");
            }

            @Override
            public ResponseVO<ProductSearchIndexVO> getSearchIndex(ProductIdDTO dto) {
                return FeignFallbackResponses.unavailable("商品服务");
            }

            @Override
            public ResponseVO<PaginationResultVO<ProductSkuListVO>> lessStockSkuPage(LessStockPageDTO dto) {
                return FeignFallbackResponses.unavailable("商品服务");
            }

            @Override
            public ResponseVO<java.util.List<String>> listOnSaleProductIds() {
                return FeignFallbackResponses.unavailable("商品服务");
            }
        };
    }
}
