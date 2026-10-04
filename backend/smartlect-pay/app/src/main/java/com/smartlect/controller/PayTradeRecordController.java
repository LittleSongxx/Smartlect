package com.smartlect.controller;

import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.PayTradeRecordService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import cn.dev33.satoken.annotation.SaCheckLogin;

@RequestMapping("/payTrade")
@RestController
public class PayTradeRecordController extends ABaseController {

    @Resource
    private PayTradeRecordService payTradeRecordService;

    @PostMapping("/loadMyTrades")
    @SaCheckLogin
    public ResponseVO loadMyTrades(Integer pageNo) {
        return getSuccessResponseVO(
                payTradeRecordService.loadUserTrades(getTokenUserInfo().getUserId(), pageNo == null ? 1 : pageNo));
    }
}
