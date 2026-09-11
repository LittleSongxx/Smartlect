package com.smartlect.api;

import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.OrderStockRestoreDTO;
import com.smartlect.api.dto.SkuStockBatchChangeDTO;
import com.smartlect.api.dto.SkuStockChangeDTO;
import com.smartlect.api.dto.SkuStockDTO;
import com.smartlect.api.dto.SkuStockQueryDTO;
import com.smartlect.api.dto.SkuStockSetDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.vo.ProductTotalStockVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.api.fallback.StockFeignFallbackFactory;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

import java.util.List;

@FeignClient(name = "smartlect-stock", contextId = "stockFeignClient", path = "/internal/stock",
        fallbackFactory = StockFeignFallbackFactory.class)
public interface StockFeignClient {

    @PostMapping("/get")
    ResponseVO<SkuStockDTO> getStock(@RequestBody SkuStockQueryDTO dto);

    @PostMapping("/getBatch")
    ResponseVO<List<SkuStockDTO>> getStockBatch(@RequestBody List<SkuStockQueryDTO> items);

    @PostMapping("/change")
    ResponseVO<StockChangeResultVO> changeStock(@RequestBody SkuStockChangeDTO dto);

    @PostMapping("/changeBatch")
    ResponseVO<StockChangeResultVO> changeStockBatch(@RequestBody SkuStockBatchChangeDTO dto);

    @PostMapping("/refund/restore")
    ResponseVO<StockChangeResultVO> restoreRefundStock(@RequestBody RefundStockRestoreDTO dto);

    @PostMapping("/order/restore")
    ResponseVO<StockChangeResultVO> restoreOrderStock(@RequestBody OrderStockRestoreDTO dto);

    @PostMapping("/order/applied")
    ResponseVO<Boolean> isOrderStockApplied(@RequestBody OrderStockRestoreDTO dto);

    @PostMapping("/refund/applied")
    ResponseVO<Boolean> isRefundStockApplied(@RequestBody RefundStockRestoreDTO dto);

    @PostMapping("/lockAndVerify")
    ResponseVO<Void> lockAndVerify(@RequestBody SkuStockBatchChangeDTO dto);

    @PostMapping("/set")
    ResponseVO<Void> setStock(@RequestBody SkuStockSetDTO dto);

    @PostMapping("/totalByProduct")
    ResponseVO<ProductTotalStockVO> totalByProduct(@RequestBody ProductIdDTO dto);

    @PostMapping("/totalByProducts")
    ResponseVO<List<ProductTotalStockVO>> totalByProducts(@RequestBody List<String> productIds);

    @PostMapping("/listLessThan")
    ResponseVO<PaginationResultVO<SkuStockDTO>> listLessThan(@RequestBody LessStockPageDTO dto);
}
