package com.smartlect.controller.admin;

import com.smartlect.entity.query.SensitiveWordQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.SensitiveWordService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/admin/sensitiveWord")
public class SensitiveWordController extends com.smartlect.controller.admin.ABaseController {

    @Resource
    private SensitiveWordService sensitiveWordService;

    @PostMapping("/list")
    public ResponseVO list(SensitiveWordQuery query) {
        PaginationResultVO result = sensitiveWordService.findListByPage(query);
        return getSuccessResponseVO(result);
    }

    @PostMapping("/save")
    public ResponseVO save(Long id, String word, String replaceWord, Integer status) {
        sensitiveWordService.save(id, word, replaceWord, status);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/delete")
    public ResponseVO delete(Long id) {
        sensitiveWordService.delete(id);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/refresh")
    public ResponseVO refresh() {
        sensitiveWordService.refreshCache();
        return getSuccessResponseVO(null);
    }
}
