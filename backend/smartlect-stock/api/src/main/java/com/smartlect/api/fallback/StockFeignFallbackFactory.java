package com.smartlect.api.fallback;

import com.smartlect.api.StockFeignClient;
import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.OrderStockRestoreDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.dto.SkuStockBatchChangeDTO;
import com.smartlect.api.dto.SkuStockChangeDTO;
import com.smartlect.api.dto.SkuStockDTO;
import com.smartlect.api.dto.SkuStockQueryDTO;
import com.smartlect.api.dto.SkuStockSetDTO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.api.vo.ProductTotalStockVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

import java.util.List;

@Slf4j
@Component
public class StockFeignFallbackFactory implements FallbackFactory<StockFeignClient> {

    @Override
    public StockFeignClient create(Throwable cause) {
        log.warn("Stock Feign fallback: {}", cause == null ? "unknown" : cause.toString());
        return new StockFeignClient() {
            @Override
            public ResponseVO<SkuStockDTO> getStock(SkuStockQueryDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<List<SkuStockDTO>> getStockBatch(List<SkuStockQueryDTO> items) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<StockChangeResultVO> changeStock(SkuStockChangeDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<StockChangeResultVO> changeStockBatch(SkuStockBatchChangeDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<StockChangeResultVO> restoreRefundStock(RefundStockRestoreDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<StockChangeResultVO> restoreOrderStock(OrderStockRestoreDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<Boolean> isOrderStockApplied(OrderStockRestoreDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<Boolean> isRefundStockApplied(RefundStockRestoreDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<Void> lockAndVerify(SkuStockBatchChangeDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<Void> setStock(SkuStockSetDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<ProductTotalStockVO> totalByProduct(ProductIdDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<List<ProductTotalStockVO>> totalByProducts(List<String> productIds) {
                return FeignFallbackResponses.unavailable("库存服务");
            }

            @Override
            public ResponseVO<PaginationResultVO<SkuStockDTO>> listLessThan(LessStockPageDTO dto) {
                return FeignFallbackResponses.unavailable("库存服务");
            }
        };
    }
}
