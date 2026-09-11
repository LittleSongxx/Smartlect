package com.smartlect.api;

import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.ProductIdListDTO;
import com.smartlect.api.dto.ProductSalesIncreaseDTO;
import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.vo.ProductSearchIndexVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.api.fallback.ProductFeignFallbackFactory;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductSkuListVO;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

import java.util.List;

@FeignClient(name = "smartlect-product", contextId = "productFeignClient", path = "/internal/product",
        fallbackFactory = ProductFeignFallbackFactory.class)
public interface ProductFeignClient {

    @PostMapping("/snapshotBatch")
    ResponseVO<ProductSnapshotBatchVO> snapshotBatch(@RequestBody ProductIdListDTO dto);

    @PostMapping("/defaultSku")
    ResponseVO<ProductSkuSnapshotVO> defaultSku(@RequestBody ProductIdDTO dto);

    @PostMapping("/increaseSales")
    ResponseVO<Void> increaseSales(@RequestBody ProductSalesIncreaseDTO dto);

    @PostMapping("/searchIndex")
    ResponseVO<ProductSearchIndexVO> getSearchIndex(@RequestBody ProductIdDTO dto);

    @PostMapping("/lessStockSkuPage")
    ResponseVO<PaginationResultVO<ProductSkuListVO>> lessStockSkuPage(@RequestBody LessStockPageDTO dto);

    @PostMapping("/listOnSaleProductIds")
    ResponseVO<List<String>> listOnSaleProductIds();
}
