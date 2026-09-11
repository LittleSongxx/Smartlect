package com.smartlect.controller;

import com.smartlect.api.vo.ServiceHealthVO;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/stock")
public class StockController extends ABaseController {

    @PostMapping("/health")
    public ResponseVO<ServiceHealthVO> health() {
        return getSuccessResponseVO(new ServiceHealthVO("smartlect-stock", "UP"));
    }
}
