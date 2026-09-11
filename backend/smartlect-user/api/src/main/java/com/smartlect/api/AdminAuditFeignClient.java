package com.smartlect.api;

import com.smartlect.api.dto.AdminAuditLogDTO;
import com.smartlect.api.fallback.AdminAuditFeignFallbackFactory;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "smartlect-admin", contextId = "adminAuditFeignClient", path = "/internal/admin/audit",
        fallbackFactory = AdminAuditFeignFallbackFactory.class)
public interface AdminAuditFeignClient {

    @PostMapping("/log")
    ResponseVO<Void> log(@RequestBody AdminAuditLogDTO dto);
}
