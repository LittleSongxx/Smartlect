package com.smartlect.controller.internal;

import com.smartlect.biz.AdminAuditLogService;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.dto.AdminAuditLogDTO;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/admin/audit")
public class AdminAuditInternalController extends ABaseController {

    @Resource
    private AdminAuditLogService adminAuditLogService;

    @PostMapping("/log")
    public ResponseVO<Void> log(@RequestBody AdminAuditLogDTO dto) {
        if (dto != null) {
            adminAuditLogService.log(dto.getOperator(), dto.getAction(), dto.getTargetUserId(), dto.getDetail());
        }
        return getSuccessResponseVO(null);
    }
}
