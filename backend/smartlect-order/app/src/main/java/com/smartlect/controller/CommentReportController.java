package com.smartlect.controller;

import com.smartlect.annotation.GlobalInterceptor;
import com.smartlect.entity.po.CommentReport;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.CommentReportService;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RequestMapping("/commentReport")
@RestController
public class CommentReportController extends ABaseController {

    @Resource
    private CommentReportService commentReportService;

    @PostMapping("/submitReport")
    @GlobalInterceptor(checkLogin = true)
    public ResponseVO submitReport(@NotEmpty String orderId,
                                   String productId,
                                   @NotEmpty @Size(max = 50) String reason,
                                   @Size(max = 500) String detail,
                                   @Size(max = 1000) String commentSnapshot) {
        String userId = getTokenUserInfo().getUserId();
        CommentReport report = commentReportService.submitReport(userId, orderId, productId, reason, detail, commentSnapshot);
        return getSuccessResponseVO(report);
    }
}
