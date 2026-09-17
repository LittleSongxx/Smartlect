package com.smartlect.controller;

import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.api.dto.BrowseHistoryMessageDTO;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.enums.ProductSortKey;
import com.smartlect.entity.enums.SortDirection;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.SimplePage;
import com.smartlect.entity.query.SysCategoryQuery;
import com.smartlect.entity.vo.Product4VO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.biz.ProductInfoService;
import com.smartlect.biz.SysCategoryService;
import com.smartlect.support.MqIdempotencyKeys;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping("/product")
@Validated
public class ProductController extends ABaseController {

    @Resource
    private SysCategoryService sysCategoryService;

    @Resource
    private ProductInfoService productInfoService;

    @Resource
    private ReliableMessageSender reliableMessageSender;

    @GetMapping("/loadCategory")
    public ResponseVO loadCategory() {
        SysCategoryQuery query = new SysCategoryQuery();
        query.setParent(true);
        query.setPropertyQuery(true);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
        return getSuccessResponseVO(sysCategoryService.findListByParam(query));
    }

    @GetMapping("/loadCommendProduct")
    public ResponseVO loadCommendProduct() {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setCommendType(1);
        query.setStatus(1);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("create_time desc"));
        query.setSimplePage(new SimplePage(0, 11));
        query.setExcludeIsolatedCatalog(true);
        return getSuccessResponseVO(productInfoService.findListByPage(query).getList());
    }

    @PostMapping("/loadProduct")
    public ResponseVO loadProduct(@NotNull Integer pageNo,
                                  String categoryId,
                                  @Size(max = 50) String keyword,
                                  BigDecimal priceFrom,
                                  BigDecimal priceTo,
                                  ProductSortKey sortKey,
                                  SortDirection sortDirection,
                                  @Size(max = 120000) String excludeProductIds) {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setPageNo(pageNo);
        query.setStatus(com.smartlect.api.enums.ProductStatusEnum.ON_SALE.getStatus());
        query.setPriceFrom(priceFrom);
        query.setPriceTo(priceTo);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of(buildProductOrderBy(sortKey, sortDirection)));
        query.setExcludeProductIdList(parseExcludeProductIds(excludeProductIds));
        query.setExcludeIsolatedCatalog(true);
        String trimmed = keyword == null ? null : keyword.trim();
        if (trimmed != null && !trimmed.isEmpty()) {
            query.setProductNameFuzzy(trimmed);
        }
        // A keyword searches the whole on-sale catalogue. Restricting to commended products
        // only makes sense for the default landing list, not for a search.
        if (categoryId == null) {
            if (trimmed == null || trimmed.isEmpty()) {
                query.setCommendType(0);
            }
            return getSuccessResponseVO(productInfoService.findListByPage(query));
        }
        query.setCategoryIdOrPCategoryId(categoryId);
        return getSuccessResponseVO(productInfoService.findListByPage(query));
    }

    static List<String> parseExcludeProductIds(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        List<String> ids = new ArrayList<>();
        for (String part : raw.split(",")) {
            String id = part.trim();
            if (id.isEmpty()) {
                continue;
            }
            if (id.length() > 64 || !id.matches("[A-Za-z0-9_-]+")) {
                continue;
            }
            ids.add(id);
            if (ids.size() >= 5000) {
                break;
            }
        }
        return ids.isEmpty() ? null : ids;
    }

    private String buildProductOrderBy(ProductSortKey sortKey, SortDirection sortDirection) {
        if (ProductSortKey.PRICE.equals(sortKey)) {
            return SortDirection.ASC.equals(sortDirection)
                    ? "min_price asc, total_sale desc"
                    : "min_price desc, total_sale desc";
        }
        if (ProductSortKey.SALE.equals(sortKey)) {
            return "total_sale desc, min_price asc";
        }
        return "commend_type desc, total_sale desc, create_time desc";
    }

    @PostMapping("/getProduct")
    public ResponseVO getProduct(@NotNull String productId) {
        Product4VO product = productInfoService.getProduct4VOByProductId(productId);
        TokenUserInfoDTO tokenUserInfo = getTokenUserInfo();
        if (tokenUserInfo != null && tokenUserInfo.getUserId() != null) {
            BrowseHistoryMessageDTO message = new BrowseHistoryMessageDTO();
            message.setUserId(tokenUserInfo.getUserId());
            message.setProductId(productId);
            long browseTime = System.currentTimeMillis();
            message.setBrowseTime(browseTime);
            reliableMessageSender.sendMessage(
                    RabbitMQConfig.BROWSE_EXCHANGE,
                    RabbitMQConfig.BROWSE_RECORD_KEY,
                    message,
                    MqIdempotencyKeys.browseRecord(
                            tokenUserInfo.getUserId(), productId, browseTime),
                    MessageReliabilityLevelEnum.HIGH);
        }
        return getSuccessResponseVO(product);
    }
}
