package com.smartlect.biz;

import com.smartlect.entity.dto.BaiduImageCensorResultDTO;
import com.smartlect.api.dto.ImageUploadResultDTO;
import com.smartlect.entity.po.ImageModerationRecord;
import com.smartlect.entity.query.ImageModerationRecordQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

public interface ImageModerationService {

    ImageUploadResultDTO uploadAndModerate(String userId, String userIp, MultipartFile file,
                                           Boolean createThumbnail, String scene, String orderId);

    BaiduImageCensorResultDTO censorImageBytes(byte[] imageBytes, String userId, String userIp);

    List<ImageModerationRecord> findListByParam(ImageModerationRecordQuery param);

    PaginationResultVO<ImageModerationRecord> findListByPage(ImageModerationRecordQuery param);

    ImageModerationRecord getByRecordId(Integer recordId);

    void handleReview(Integer recordId, String action, String handleRemark);

    void validateCommentQuarantinePaths(String userId, String orderId, String commentImages);

    boolean containsQuarantinePath(String commentImages);

    int cleanupOrphanedCommentUploads();

}
