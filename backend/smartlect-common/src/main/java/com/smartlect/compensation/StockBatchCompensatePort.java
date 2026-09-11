package com.smartlect.compensation;

import com.smartlect.entity.po.ProductItem;

import java.util.List;

public interface StockBatchCompensatePort {

    int changeStockBatch(List<ProductItem> items);

    int restoreOrderStock(String payOrderId, List<ProductItem> items);
}
